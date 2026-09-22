"""
📋 AI Voice-Controlled Kanban Board — Full Application
Combines browser-native SpeechRecognition, custom Gradio 6 reactive HTML component,
and dual LLM intent parsing (OpenAI + Google Gemini with local heuristic fallback).
"""

import copy
import json
import os
import re
import uuid
import gradio as gr
from dotenv import load_dotenv
from ai_service import parse_voice_command

load_dotenv()

# ─── HTML & CSS Component Templates ───────────────────────────────

HTML_TEMPLATE = """
<div class="kanban-wrapper">
    ${(() => {
        window.__esc = window.__esc || function(s) {
            if (!s && s !== 0) return '';
            return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
        };
        return '';
    })()}
    <div class="kanban-header">
        <div class="header-left">
            <h2>${board_title}</h2>
            <span class="board-badge">AI Voice-Enabled</span>
        </div>
        <div class="header-right">
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" class="search-input" placeholder="Filter tasks..." />
            </div>
            <div class="header-stats">
                ${(() => {
                    const cols = (value && value.columns) || [];
                    const total = cols.reduce((sum, col) => sum + (col.cards ? col.cards.length : 0), 0);
                    const done = cols.find(c => c.id === 'done');
                    const doneCount = done && done.cards ? done.cards.length : 0;
                    const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0;
                    return '<span class="stat-pill">📊 ' + total + ' tasks</span>' +
                           '<span class="stat-pill done-pill">✅ ' + doneCount + ' done (' + pct + '%)</span>';
                })()}
            </div>
        </div>
    </div>

    <div class="progress-track" title="Overall completion progress">
        ${(() => {
            const cols = (value && value.columns) || [];
            const total = cols.reduce((sum, col) => sum + (col.cards ? col.cards.length : 0), 0);
            const done = cols.find(c => c.id === 'done');
            const doneCount = done && done.cards ? done.cards.length : 0;
            const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0;
            return '<div class="progress-bar" style="width: ' + pct + '%"></div>';
        })()}
    </div>

    <div class="kanban-board">
        ${((value && value.columns) || []).map((col, colIdx) => `
            <div class="kanban-column ${col.collapsed ? 'collapsed' : ''}" data-col-idx="${colIdx}" data-col-id="${col.id}">
                <div class="column-header" style="border-top: 3px solid ${col.color}">
                    <div class="col-header-left">
                        <button class="collapse-btn" data-col-idx="${colIdx}" title="${col.collapsed ? 'Expand column' : 'Collapse column'}">
                            ${col.collapsed ? '▶' : '▼'}
                        </button>
                        <span class="col-title">${window.__esc(col.title)}</span>
                    </div>
                    <span class="col-count" style="background: ${col.color}22; color: ${col.color}">
                        ${col.cards ? col.cards.length : 0}
                    </span>
                </div>
                <div class="card-list ${col.collapsed ? 'hidden' : ''}" data-col-idx="${colIdx}">
                    ${(col.cards || []).map((card, cardIdx) => `
                        <div class="kanban-card" draggable="true" data-col-idx="${colIdx}" data-card-idx="${cardIdx}" data-card-id="${card.id}">
                            <div class="card-priority priority-${card.priority || 'medium'}"></div>
                            <div class="card-content">
                                <div class="card-text" data-col-idx="${colIdx}" data-card-idx="${cardIdx}" title="Click to edit text">
                                    ${window.__esc(card.text)}
                                </div>
                                <div class="card-footer">
                                    <div class="card-tags">
                                        ${(card.tags || []).map(t => '<span class="tag">' + window.__esc(t) + '</span>').join('')}
                                    </div>
                                    <div class="card-actions">
                                        <button class="priority-cycle" data-col-idx="${colIdx}" data-card-idx="${cardIdx}" title="Cycle priority: High / Med / Low">
                                            ${card.priority === 'high' ? '🔴' : card.priority === 'low' ? '🟢' : '🟡'}
                                        </button>
                                        <button class="delete-card" data-col-idx="${colIdx}" data-card-idx="${cardIdx}" title="Delete card">✕</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
                <div class="add-card-area ${col.collapsed ? 'hidden' : ''}">
                    <input type="text" class="add-card-input" data-col-idx="${colIdx}" placeholder="+ Add card… (press Enter)" />
                </div>
            </div>
        `).join('')}
    </div>
</div>
"""

CSS_TEMPLATE = """
    .kanban-wrapper {
        background: linear-gradient(135deg, #0b0f19 0%, #161f30 100%);
        border: 1px solid #1e293b;
        border-radius: 16px;
        padding: 24px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        color: #e2e8f0;
        overflow-x: auto;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    }
    .kanban-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        flex-wrap: wrap;
        gap: 16px;
    }
    .header-left {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .kanban-header h2 {
        margin: 0;
        font-size: 24px;
        font-weight: 700;
        color: #f8fafc;
        letter-spacing: -0.5px;
    }
    .board-badge {
        font-size: 11px;
        text-transform: uppercase;
        font-weight: 700;
        letter-spacing: 0.8px;
        background: rgba(99, 102, 241, 0.15);
        color: #818cf8;
        border: 1px solid rgba(99, 102, 241, 0.3);
        padding: 3px 8px;
        border-radius: 6px;
    }
    .header-right {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
    }

    .search-box {
        display: flex;
        align-items: center;
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 6px 14px;
        transition: all 0.2s ease;
    }
    .search-box:focus-within {
        border-color: #6366f1;
        background: rgba(99, 102, 241, 0.08);
        box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
    }
    .search-icon {
        font-size: 13px;
        margin-right: 8px;
        opacity: 0.7;
    }
    .search-input {
        background: none;
        border: none;
        color: #f1f5f9;
        font-size: 13px;
        outline: none;
        width: 160px;
    }
    .search-input::placeholder {
        color: #64748b;
    }

    .header-stats {
        display: flex;
        gap: 8px;
    }
    .stat-pill {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 6px 14px;
        border-radius: 12px;
        font-size: 13px;
        color: #94a3b8;
        font-weight: 500;
    }
    .done-pill {
        color: #34d399;
        border-color: rgba(52, 211, 153, 0.2);
        background: rgba(52, 211, 153, 0.05);
    }

    .progress-track {
        height: 6px;
        background: rgba(255, 255, 255, 0.06);
        border-radius: 6px;
        margin-bottom: 22px;
        overflow: hidden;
    }
    .progress-bar {
        height: 100%;
        background: linear-gradient(90deg, #6366f1 0%, #10b981 100%);
        transition: width 0.4s ease;
        border-radius: 6px;
    }

    .kanban-board {
        display: flex;
        gap: 16px;
        align-items: flex-start;
        min-height: 480px;
    }

    .kanban-column {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        width: 300px;
        min-width: 300px;
        display: flex;
        flex-direction: column;
        transition: all 0.2s ease;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    .kanban-column.collapsed {
        width: 54px;
        min-width: 54px;
    }
    .kanban-column.drag-over {
        border-color: #6366f1;
        background: #25334d;
        box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.4);
    }

    .column-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 14px 16px;
        background: rgba(15, 23, 42, 0.4);
        border-top-left-radius: 11px;
        border-top-right-radius: 11px;
    }
    .col-header-left {
        display: flex;
        align-items: center;
        gap: 8px;
        overflow: hidden;
    }
    .collapse-btn {
        background: none;
        border: none;
        color: #94a3b8;
        cursor: pointer;
        font-size: 11px;
        padding: 2px;
        line-height: 1;
        transition: color 0.15s;
    }
    .collapse-btn:hover {
        color: #f8fafc;
    }
    .col-title {
        font-weight: 600;
        font-size: 15px;
        color: #f1f5f9;
        white-space: nowrap;
        text-overflow: ellipsis;
        overflow: hidden;
    }
    .col-count {
        font-size: 12px;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 20px;
    }

    .card-list {
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        min-height: 80px;
        max-height: 600px;
        overflow-y: auto;
    }
    .card-list.hidden, .add-card-area.hidden {
        display: none !important;
    }

    .kanban-card {
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 10px;
        display: flex;
        overflow: hidden;
        cursor: grab;
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        position: relative;
    }
    .kanban-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.35);
        border-color: #475569;
    }
    .kanban-card.dragging {
        opacity: 0.4;
        cursor: grabbing;
        transform: scale(0.98);
    }
    .kanban-card.search-hidden {
        display: none !important;
    }
    .kanban-card.search-highlight {
        border-color: #f59e0b;
        box-shadow: 0 0 10px rgba(245, 158, 11, 0.25);
    }

    .card-priority {
        width: 5px;
        flex-shrink: 0;
    }
    .priority-high { background: #ef4444; }
    .priority-medium { background: #f59e0b; }
    .priority-low { background: #10b981; }

    .card-content {
        padding: 12px 14px;
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    .card-text {
        font-size: 14px;
        color: #f1f5f9;
        line-height: 1.45;
        cursor: text;
        word-break: break-word;
        outline: none;
    }
    .card-text.editing {
        background: #1e293b;
        padding: 4px 6px;
        border-radius: 4px;
        box-shadow: 0 0 0 1px #6366f1;
    }

    .card-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
    }
    .card-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
    }
    .tag {
        font-size: 11px;
        background: rgba(255, 255, 255, 0.08);
        color: #94a3b8;
        padding: 2px 7px;
        border-radius: 5px;
    }

    .card-actions {
        display: flex;
        align-items: center;
        gap: 4px;
        opacity: 0.6;
        transition: opacity 0.15s;
    }
    .kanban-card:hover .card-actions {
        opacity: 1;
    }
    .priority-cycle, .delete-card {
        background: none;
        border: none;
        cursor: pointer;
        font-size: 12px;
        padding: 2px 4px;
        border-radius: 4px;
        color: #94a3b8;
        line-height: 1;
    }
    .priority-cycle:hover {
        background: rgba(255, 255, 255, 0.1);
    }
    .delete-card:hover {
        background: rgba(239, 68, 68, 0.2);
        color: #f87171;
    }

    .add-card-area {
        padding: 8px 12px 12px 12px;
    }
    .add-card-input {
        width: 100%;
        background: rgba(15, 23, 42, 0.5);
        border: 1px dashed #334155;
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 13px;
        color: #f1f5f9;
        outline: none;
        box-sizing: border-box;
        transition: all 0.2s;
    }
    .add-card-input:focus {
        border-color: #6366f1;
        border-style: solid;
        background: rgba(15, 23, 42, 0.8);
    }
    .add-card-input::placeholder {
        color: #64748b;
    }
"""

JS_ON_LOAD = """
    // ─── Drag and Drop Logic ───────────────────────────────────────
    let draggedCard = null;
    let sourceColIdx = null;
    let sourceCardIdx = null;

    element.addEventListener('dragstart', (e) => {
        const cardEl = e.target.closest('.kanban-card');
        if (!cardEl) return;
        draggedCard = cardEl;
        sourceColIdx = parseInt(cardEl.dataset.colIdx);
        sourceCardIdx = parseInt(cardEl.dataset.cardIdx);
        cardEl.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', '');
    });

    element.addEventListener('dragend', (e) => {
        const cardEl = e.target.closest('.kanban-card');
        if (cardEl) cardEl.classList.remove('dragging');
        element.querySelectorAll('.kanban-column').forEach(c => c.classList.remove('drag-over'));
        draggedCard = null;
    });

    element.addEventListener('dragover', (e) => {
        const colEl = e.target.closest('.kanban-column');
        if (!colEl) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        colEl.classList.add('drag-over');
    });

    element.addEventListener('dragleave', (e) => {
        const colEl = e.target.closest('.kanban-column');
        if (colEl && !colEl.contains(e.relatedTarget)) {
            colEl.classList.remove('drag-over');
        }
    });

    element.addEventListener('drop', (e) => {
        e.preventDefault();
        const colEl = e.target.closest('.kanban-column');
        if (!colEl || sourceColIdx === null) return;
        colEl.classList.remove('drag-over');

        const targetColIdx = parseInt(colEl.dataset.colIdx);
        if (isNaN(targetColIdx)) return;

        // Perform mutation in deep copied props.value
        const nv = JSON.parse(JSON.stringify(props.value));
        const [movedCard] = nv.columns[sourceColIdx].cards.splice(sourceCardIdx, 1);
        if (!movedCard) return;

        // Check if dropped near another card in target column
        const afterCardEl = e.target.closest('.kanban-card');
        if (afterCardEl && afterCardEl !== draggedCard) {
            const afterCardIdx = parseInt(afterCardEl.dataset.cardIdx);
            nv.columns[targetColIdx].cards.splice(afterCardIdx, 0, movedCard);
        } else {
            nv.columns[targetColIdx].cards.push(movedCard);
        }

        props.value = nv;
        trigger('change');
    });

    // ─── Click Actions (Delete, Priority Cycle, Collapse) ─────────
    element.addEventListener('click', (e) => {
        // Delete Card
        const delBtn = e.target.closest('.delete-card');
        if (delBtn) {
            const colIdx = parseInt(delBtn.dataset.colIdx);
            const cardIdx = parseInt(delBtn.dataset.cardIdx);
            const nv = JSON.parse(JSON.stringify(props.value));
            nv.columns[colIdx].cards.splice(cardIdx, 1);
            props.value = nv;
            trigger('change');
            return;
        }

        // Priority Cycle: high -> medium -> low -> high
        const prioBtn = e.target.closest('.priority-cycle');
        if (prioBtn) {
            const colIdx = parseInt(prioBtn.dataset.colIdx);
            const cardIdx = parseInt(prioBtn.dataset.cardIdx);
            const nv = JSON.parse(JSON.stringify(props.value));
            const card = nv.columns[colIdx].cards[cardIdx];
            const cycle = { 'high': 'medium', 'medium': 'low', 'low': 'high' };
            card.priority = cycle[card.priority || 'medium'] || 'medium';
            props.value = nv;
            trigger('change');
            return;
        }

        // Collapse / Expand Column
        const colBtn = e.target.closest('.collapse-btn');
        if (colBtn) {
            const colIdx = parseInt(colBtn.dataset.colIdx);
            const nv = JSON.parse(JSON.stringify(props.value));
            nv.columns[colIdx].collapsed = !nv.columns[colIdx].collapsed;
            props.value = nv;
            trigger('change');
            return;
        }

        // Inline Edit Text
        const textEl = e.target.closest('.card-text');
        if (textEl && !textEl.classList.contains('editing')) {
            textEl.contentEditable = 'true';
            textEl.classList.add('editing');
            textEl.focus();
        }
    });

    // Commit inline edit
    function commitEdit(textEl) {
        textEl.contentEditable = 'false';
        textEl.classList.remove('editing');
        const colIdx = parseInt(textEl.dataset.colIdx);
        const cardIdx = parseInt(textEl.dataset.cardIdx);
        const newText = textEl.innerText.trim();
        if (!newText) return;
        const nv = JSON.parse(JSON.stringify(props.value));
        if (nv.columns[colIdx] && nv.columns[colIdx].cards[cardIdx]) {
            nv.columns[colIdx].cards[cardIdx].text = newText;
            props.value = nv;
            trigger('change');
        }
    }

    element.addEventListener('blur', (e) => {
        if (e.target.classList && e.target.classList.contains('editing')) {
            commitEdit(e.target);
        }
    }, true);

    element.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.classList.contains('editing')) {
            e.preventDefault();
            e.target.blur();
            return;
        }

        if (e.key === 'Enter' && e.target.classList.contains('add-card-input')) {
            const text = e.target.value.trim();
            if (!text) return;
            const colIdx = parseInt(e.target.dataset.colIdx);
            const nv = JSON.parse(JSON.stringify(props.value));
            nv.columns[colIdx].cards.push({
                id: String(Date.now()).slice(-8),
                text: text,
                priority: 'medium',
                tags: []
            });
            props.value = nv;
            e.target.value = '';
            trigger('change');
        }
    });

    // ─── Instant Search Filter ────────────────────────────────────
    element.addEventListener('input', (e) => {
        if (!e.target.classList.contains('search-input')) return;
        const q = e.target.value.toLowerCase().trim();
        element.querySelectorAll('.kanban-card').forEach(card => {
            const text = (card.querySelector('.card-text')?.innerText || '').toLowerCase();
            const tags = Array.from(card.querySelectorAll('.tag')).map(t => t.innerText.toLowerCase()).join(' ');
            const match = !q || text.includes(q) || tags.includes(q);
            card.classList.toggle('search-hidden', !match);
            card.classList.toggle('search-highlight', !!q && match);
        });
    });

    // ─── Voice Control & Speech Recognition Bridge ────────────────
    (function setupVoiceControl() {
        if (document.getElementById('floating-mic-btn')) return;

        const micBtn = document.createElement('button');
        micBtn.id = 'floating-mic-btn';
        micBtn.innerText = '🎤';
        micBtn.title = 'Click to speak a Kanban voice command';
        micBtn.style.cssText = `
            position: fixed;
            bottom: 32px;
            right: 32px;
            width: 64px;
            height: 64px;
            border-radius: 50%;
            border: none;
            background: #6366f1;
            color: white;
            font-size: 26px;
            cursor: pointer;
            box-shadow: 0 6px 24px rgba(99, 102, 241, 0.55);
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 99999;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        document.body.appendChild(micBtn);

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            micBtn.title = 'Speech recognition not supported in this browser. Please use Chrome or Edge.';
            micBtn.style.background = '#475569';
            micBtn.style.opacity = '0.7';
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.lang = 'en-US';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        let isListening = false;

        micBtn.addEventListener('click', () => {
            if (isListening) return;
            try {
                isListening = true;
                micBtn.innerText = '🔴';
                micBtn.style.background = '#ef4444';
                micBtn.style.boxShadow = '0 6px 28px rgba(239, 68, 68, 0.7)';
                micBtn.style.transform = 'scale(1.08)';
                recognition.start();
            } catch (err) {
                console.error('Error starting recognition:', err);
                isListening = false;
                micBtn.innerText = '🎤';
                micBtn.style.background = '#6366f1';
                micBtn.style.transform = 'scale(1)';
            }
        });

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            console.log('Spoken Transcript:', transcript);

            // Processing state
            micBtn.innerText = '⏳';
            micBtn.style.background = '#f59e0b';
            micBtn.style.boxShadow = '0 6px 28px rgba(245, 158, 11, 0.65)';
            micBtn.style.transform = 'scale(1)';

            // Set value in Gradio Textbox using Svelte property descriptor setter
            const voiceBox = document.querySelector('#voice-input textarea, #voice-input input');
            if (voiceBox) {
                const proto = Object.getPrototypeOf(voiceBox);
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) {
                    setter.call(voiceBox, transcript);
                } else {
                    voiceBox.value = transcript;
                }
                voiceBox.dispatchEvent(new Event('input', { bubbles: true }));
                voiceBox.dispatchEvent(new Event('change', { bubbles: true }));
            }

            // Programmatically click Execute button
            setTimeout(() => {
                const executeBtn = document.querySelector('#execute-btn button') ||
                                   document.querySelector('#execute-btn') ||
                                   Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Execute'));
                if (executeBtn) {
                    executeBtn.click();
                }

                // Reset mic state
                setTimeout(() => {
                    micBtn.innerText = '🎤';
                    micBtn.style.background = '#6366f1';
                    micBtn.style.boxShadow = '0 6px 24px rgba(99, 102, 241, 0.55)';
                    isListening = false;
                }, 4000);
            }, 300);
        };

        recognition.onend = () => {
            if (isListening && micBtn.innerText === '🔴') {
                isListening = false;
                micBtn.innerText = '🎤';
                micBtn.style.background = '#6366f1';
                micBtn.style.boxShadow = '0 6px 24px rgba(99, 102, 241, 0.55)';
                micBtn.style.transform = 'scale(1)';
            }
        };

        recognition.onerror = (event) => {
            console.warn('Speech recognition warning/error:', event.error);
            isListening = false;
            micBtn.innerText = '🎤';
            micBtn.style.background = '#6366f1';
            micBtn.style.boxShadow = '0 6px 24px rgba(99, 102, 241, 0.55)';
            micBtn.style.transform = 'scale(1)';
        };
    })();
"""

# ─── Custom Gradio Component ───────────────────────────────────────

class KanbanBoard(gr.HTML):
    """Custom drag-and-drop reactive Kanban board component for Gradio 6."""

    def __init__(self, value=None, board_title="My Project Board", **kwargs):
        if value is None:
            value = {
                "columns": [
                    {
                        "id": "todo",
                        "title": "📋 To Do",
                        "color": "#6366f1",
                        "collapsed": False,
                        "cards": [
                            {"id": "c1", "text": "Research gr.HTML reactive component", "priority": "high", "tags": ["gradio", "ui"]},
                            {"id": "c2", "text": "Design glassmorphic dark theme", "priority": "medium", "tags": ["design"]},
                            {"id": "c3", "text": "Write project README documentation", "priority": "low", "tags": ["docs"]},
                        ],
                    },
                    {
                        "id": "progress",
                        "title": "🔨 In Progress",
                        "color": "#f59e0b",
                        "collapsed": False,
                        "cards": [
                            {"id": "c4", "text": "Build AI voice dispatcher & fuzzy matching", "priority": "high", "tags": ["backend", "ai"]},
                        ],
                    },
                    {
                        "id": "review",
                        "title": "👀 Review",
                        "color": "#8b5cf6",
                        "collapsed": False,
                        "cards": [
                            {"id": "c5", "text": "Test Web Speech API integration", "priority": "medium", "tags": ["testing"]},
                        ],
                    },
                    {
                        "id": "done",
                        "title": "✅ Done",
                        "color": "#10b981",
                        "collapsed": False,
                        "cards": [
                            {"id": "c6", "text": "Initialize project repository", "priority": "medium", "tags": ["setup"]},
                        ],
                    },
                ],
            }

        super().__init__(
            value=value,
            board_title=board_title,
            html_template=HTML_TEMPLATE,
            css_template=CSS_TEMPLATE,
            js_on_load=JS_ON_LOAD,
            **kwargs,
        )

    def api_info(self):
        return {"type": "object", "description": "Kanban board state representation with columns and cards"}


# ─── Preset Boards & Action Dispatcher ────────────────────────────
from kanban_actions import PRESET_BOARDS, _find_card, action_dispatcher



# ─── Event Handlers ────────────────────────────────────────────────

def handle_voice(transcript: str, board_state: dict, provider_selection: str):
    """Process voice command input, parse action, mutate state, and report status."""
    if not transcript or not transcript.strip():
        return gr.HTML(), "Click the mic or type a command above."

    # Map provider dropdown selection
    pref = "auto"
    if "OpenAI" in provider_selection:
        pref = "openai"
    elif "Gemini" in provider_selection:
        pref = "gemini"
    elif "Local" in provider_selection:
        pref = "local"

    action, engine_name = parse_voice_command(transcript, board_state, preferred_provider=pref)
    new_state, status_msg = action_dispatcher(action, board_state)
    
    audit_log = f'🎙️ Heard: "{transcript}"\n🤖 Processed via: {engine_name}\n{status_msg}'
    return gr.HTML(value=new_state), audit_log


def _load_preset_board(preset_name: str, title: str):
    """Load selected preset board."""
    data = PRESET_BOARDS.get(preset_name, PRESET_BOARDS["🚀 Product Launch"])
    total = sum(len(col.get("cards", [])) for col in data.get("columns", []))
    msg = f"📌 Loaded '{preset_name}' preset ({total} tasks across {len(data['columns'])} columns)."
    return gr.HTML(value=data, board_title=title), msg


def _on_board_change(board_val: dict):
    """Update status bar stats whenever board is modified interactively."""
    if isinstance(board_val, dict) and "columns" in board_val:
        cols = board_val["columns"]
        total = sum(len(col.get("cards", [])) for col in cols)
        done = next((col for col in cols if col.get("id") == "done"), None)
        done_count = len(done.get("cards", [])) if done else 0
        pct = round((done_count / total) * 100) if total > 0 else 0
        breakdown = "  |  ".join([f"{col.get('title', '?')}: {len(col.get('cards', []))}" for col in cols])
        return f"📊 Board State: {total} total tasks · {done_count} completed ({pct}%)  ·  {breakdown}"
    return "Ready."


# ─── Gradio Application Assembly ───────────────────────────────────

def create_app():
    with gr.Blocks(title="AI Voice-Controlled Kanban App") as demo:
        gr.Markdown(
            """
            # 🎙️ AI Voice-Controlled Kanban App
            ### Manage your agile sprint hands-free with AI Speech Recognition & Reactive Gradio 6
            """
        )

        with gr.Row():
            preset_dropdown = gr.Dropdown(
                choices=list(PRESET_BOARDS.keys()),
                value="🚀 Product Launch",
                label="📁 Template Presets",
                scale=2,
            )
            title_input = gr.Textbox(
                value="Sprint Board",
                label="🏷️ Board Title",
                scale=2,
            )
            load_btn = gr.Button("🔄 Load Preset", scale=1)

        # Main reactive Kanban Board
        board = KanbanBoard(
            value=PRESET_BOARDS["🚀 Product Launch"],
            board_title="Sprint Board"
        )

        with gr.Row():
            voice_input = gr.Textbox(
                label="🗣️ Voice / Text Command",
                placeholder="Click the floating 🎤 button in the corner to speak, or type here (e.g. 'move Fix login bug to done')...",
                elem_id="voice-input",
                scale=4,
            )
            ai_provider_dropdown = gr.Dropdown(
                choices=["Auto Detect", "OpenAI (gpt-4o)", "Google Gemini (gemini-2.5-flash)", "Local Rule Engine"],
                value="Auto Detect",
                label="🧠 AI Intent Engine",
                scale=1,
            )
            execute_btn = gr.Button("▶ Execute", variant="primary", scale=1, elem_id="execute-btn")

        status = gr.Textbox(
            label="⚡ AI Activity Log & Confirmation",
            value="Ready. Click the floating microphone button or type a command above.",
            elem_id="status-bar",
            interactive=False,
            lines=2,
        )

        # Wire events
        execute_btn.click(
            fn=handle_voice,
            inputs=[voice_input, board, ai_provider_dropdown],
            outputs=[board, status]
        )
        voice_input.submit(
            fn=handle_voice,
            inputs=[voice_input, board, ai_provider_dropdown],
            outputs=[board, status]
        )
        load_btn.click(
            fn=_load_preset_board,
            inputs=[preset_dropdown, title_input],
            outputs=[board, status]
        )
        board.change(
            fn=_on_board_change,
            inputs=board,
            outputs=status
        )

    return demo


if __name__ == "__main__":
    app = create_app()
    auth_user = os.environ.get("GRADIO_AUTH_USER")
    auth_pass = os.environ.get("GRADIO_AUTH_PASSWORD")
    if auth_user and auth_pass:
        print(f"🔒 Launching Gradio with Basic Authentication for user: {auth_user}")
        app.launch(auth=(auth_user, auth_pass))
    else:
        app.launch()
