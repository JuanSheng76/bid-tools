/**
 * 标策台 - 客户端交互逻辑
 */

// ====== Toast 提示 ======
let _toastTimer = null;

function showToast(message, type = 'info', duration = 2500) {
    // 移除旧 toast
    const old = document.querySelector('.toast');
    if (old) {
        old.style.animation = 'slideOut 0.25s ease-in forwards';
        setTimeout(() => old.remove(), 260);
    }
    clearTimeout(_toastTimer);

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    _toastTimer = setTimeout(() => {
        toast.style.animation = 'slideOut 0.25s ease-in forwards';
        setTimeout(() => toast.remove(), 260);
    }, duration);
}

// ====== Kanban 拖拽 (SortableJS + fetch) ======
function initKanban() {
    if (typeof Sortable === 'undefined') return;
    document.querySelectorAll('.sortable-list').forEach(el => {
        if (el._sortable) return; // 防止重复初始化
        el._sortable = new Sortable(el, {
            group: 'tasks',
            animation: 200,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            dragClass: 'sortable-drag',
            onEnd: function(evt) {
                const taskId = evt.item.dataset.taskId;
                const newStatus = evt.to.dataset.status;
                if (taskId && newStatus) {
                    updateTaskStatus(taskId, newStatus, {
                        item: evt.item,
                        from: evt.from,
                        oldIndex: evt.oldIndex,
                    });
                }
            }
        });
    });
}

// ====== 更新任务状态 ======
function updateTaskStatus(taskId, status, dragContext = null) {
    const formData = new FormData();
    formData.append('status', status);

    return fetch(`/tasks/${taskId}/status`, {
        method: 'POST',
        body: formData,
    })
    .then(async res => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '更新失败');
        return data;
    })
    .then(data => {
        if (data.success) {
            const card = dragContext?.item || document.querySelector(`[data-task-id="${taskId}"]`);
            if (card && !dragContext) {
                const target = document.querySelector(`.sortable-list[data-status="${status}"]`);
                if (target) target.appendChild(card);
            }
            if (card) {
                card.classList.toggle('task-card--done', status === 'done');
                card.style.opacity = status === 'done' ? '0.72' : '';
                const title = card.querySelector('.task-title');
                if (title) title.style.textDecoration = status === 'done' ? 'line-through' : '';
                const select = card.querySelector('select[data-status-control]');
                if (select) select.value = status;
            }
            updateKanbanCounts();
            showToast('任务状态已更新', 'success');
        } else {
            throw new Error(data.error || '更新失败');
        }
    })
    .catch(err => {
        if (dragContext?.item && dragContext?.from) {
            const before = dragContext.from.children[dragContext.oldIndex] || null;
            dragContext.from.insertBefore(dragContext.item, before);
        }
        updateKanbanCounts();
        showToast(err.message || '网络错误', 'error');
        console.error(err);
    });
}

function updateKanbanCounts() {
    document.querySelectorAll('.kanban-col').forEach(col => {
        const count = col.querySelector('.count');
        const total = col.querySelectorAll('.task-card').length;
        if (count) count.textContent = total;
        const empty = col.querySelector('.empty-state');
        if (empty) empty.style.display = total ? 'none' : '';
    });
}

// ====== 分配任务 ======
function assignTask(taskId, assigneeId) {
    const formData = new FormData();
    formData.append('assignee_id', assigneeId);

    fetch(`/tasks/${taskId}/assign`, {
        method: 'POST',
        body: formData,
    })
    .then(res => res.text())
    .then(html => {
        document.getElementById('assignee-display').innerHTML = html || '未分配';
        showToast('分配成功', 'success');
    })
    .catch(err => {
        showToast('分配失败', 'error');
        console.error(err);
    });
}

// ====== Checklist (Alpine.js) ======
function checklistApp(taskId, initialItems) {
    return {
        taskId: taskId,
        items: initialItems || [],
        newText: '',

        save() {
            fetch(`/tasks/${this.taskId}/checklist`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ checklist: this.items }),
            })
            .then(res => res.json())
            .then(data => {
                if (!data.success) showToast('保存失败', 'error');
            })
            .catch(err => console.error(err));
        },

        add() {
            if (!this.newText.trim()) return;
            this.items.push({ text: this.newText.trim(), done: false });
            this.newText = '';
            this.save();
        },

        remove(idx) {
            this.items.splice(idx, 1);
            this.save();
        }
    };
}

// ====== Inline Checklist (看板卡片内联，Alpine.js) ======
function inlineChecklist(taskId) {
    return {
        taskId: taskId,
        items: [],

        init() {
            try {
                const raw = this.$el.dataset.checklist;
                this.items = JSON.parse(raw || '[]');
            } catch (e) {
                console.error('inlineChecklist: JSON parse error', e);
                this.items = [];
            }
        },

        get doneCount() {
            return this.items.filter(i => i.done).length;
        },

        save() {
            fetch(`/tasks/${this.taskId}/checklist`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ checklist: this.items }),
            })
            .then(res => res.json())
            .then(data => {
                if (!data.success) showToast('保存失败', 'error');
            })
            .catch(err => console.error(err));
        },
    };
}

// ====== Kanban (Alpine.js) ======
function kanbanApp() {
    return {
        init() {
            this.$nextTick(() => initKanban());
        }
    };
}

// ====== 初始化 ======
document.addEventListener('DOMContentLoaded', () => {
    initKanban();

    const dialog = document.getElementById('confirm-dialog');
    let pendingForm = null;
    document.addEventListener('submit', (event) => {
        const form = event.target.closest('form[data-confirm]');
        if (!form || form.dataset.confirmed === 'true' || !dialog) return;
        event.preventDefault();
        pendingForm = form;
        document.getElementById('confirm-message').textContent =
            form.dataset.confirm || '确定继续吗？';
        dialog.showModal();
    });
    dialog?.querySelector('[data-confirm-cancel]')?.addEventListener('click', () => {
        pendingForm = null;
        dialog.close();
    });
    dialog?.querySelector('[data-confirm-accept]')?.addEventListener('click', () => {
        if (!pendingForm) return;
        pendingForm.dataset.confirmed = 'true';
        dialog.close();
        pendingForm.requestSubmit();
        pendingForm = null;
    });
    dialog?.addEventListener('click', (event) => {
        if (event.target === dialog) {
            pendingForm = null;
            dialog.close();
        }
    });

    document.querySelectorAll('[data-collapse-column]').forEach(button => {
        button.addEventListener('click', () => {
            const column = button.closest('.kanban-col');
            const collapsed = column.classList.toggle('is-collapsed');
            button.textContent = collapsed ? '展开' : '收起';
            button.setAttribute('aria-expanded', String(!collapsed));
            button.setAttribute('aria-label', collapsed ? '展开已完成任务' : '收起已完成任务');
        });
    });

    document.querySelectorAll('[data-password-toggle]').forEach(button => {
        button.addEventListener('click', () => {
            const input = document.getElementById(button.dataset.passwordToggle);
            if (!input) return;
            const reveal = input.type === 'password';
            input.type = reveal ? 'text' : 'password';
            button.textContent = reveal ? '隐藏' : '显示';
        });
    });
});

// ====== HTMX 事件 ======
document.body.addEventListener('htmx:beforeSwap', () => {
    // 页面切换前淡出效果
    const content = document.querySelector('.content');
    if (content) content.style.opacity = '0.5';
});

document.body.addEventListener('htmx:afterSwap', () => {
    initKanban();
    // 淡入
    const content = document.querySelector('.content');
    if (content) {
        content.style.transition = 'opacity 0.2s ease-in';
        content.style.opacity = '1';
    }
});

// ====== 键盘快捷键 ======
document.addEventListener('keydown', (e) => {
    // Ctrl+K 聚焦搜索（如果在标讯页面）
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        const searchInput = document.querySelector('input[name="keyword"]');
        if (searchInput) {
            e.preventDefault();
            searchInput.focus();
        }
    }
    // Escape 关闭 toast
    if (e.key === 'Escape') {
        const toast = document.querySelector('.toast');
        if (toast) {
            toast.style.animation = 'slideOut 0.25s ease-in forwards';
            setTimeout(() => toast.remove(), 260);
        }
    }
});
