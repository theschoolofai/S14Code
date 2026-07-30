// ========== KANBAN BOARD RENDERER ==========
// Pure DOM renderer - executes no value, draws from text nodes only
// Location: s13code/ui/client/components/KanbanBoard.js

export function renderKanbanBoard(element, props) {
    const { columns, cards, title, onCardMove, onCardClick, onColumnClick } = props;
    
    // Clear element
    element.innerHTML = '';
    
    // Create container
    const container = document.createElement('div');
    container.className = 'kanban-board';
    
    // Title
    if (title) {
        const header = document.createElement('h3');
        header.className = 'kanban-title';
        header.textContent = title;
        container.appendChild(header);
    }
    
    // Board wrapper
    const board = document.createElement('div');
    board.className = 'kanban-board-wrapper';
    board.style.display = 'flex';
    board.style.gap = '16px';
    board.style.padding = '16px';
    board.style.overflowX = 'auto';
    board.style.alignItems = 'flex-start';
    
    // Create columns
    columns.forEach(column => {
        const colEl = document.createElement('div');
        colEl.className = 'kanban-column';
        colEl.dataset.columnId = column.id;
        colEl.style.minWidth = '280px';
        colEl.style.maxWidth = '320px';
        colEl.style.flex = '1';
        colEl.style.background = '#f8f9fa';
        colEl.style.borderRadius = '8px';
        colEl.style.padding = '12px';
        colEl.style.border = '1px solid #e9ecef';
        
        if (column.color) {
            colEl.style.borderTop = '4px solid ' + column.color;
        }
        
        // Column header
        const headerEl = document.createElement('div');
        headerEl.className = 'kanban-column-header';
        headerEl.style.display = 'flex';
        headerEl.style.justifyContent = 'space-between';
        headerEl.style.alignItems = 'center';
        headerEl.style.marginBottom = '12px';
        headerEl.style.fontWeight = '600';
        headerEl.style.fontSize = '14px';
        headerEl.style.color = '#495057';
        headerEl.textContent = column.title;
        
        if (column.limit) {
            const limitBadge = document.createElement('span');
            limitBadge.className = 'kanban-limit-badge';
            const cardCount = cards.filter(c => c.columnId === column.id).length;
            limitBadge.textContent = cardCount + '/' + column.limit;
            limitBadge.style.background = '#e9ecef';
            limitBadge.style.padding = '2px 8px';
            limitBadge.style.borderRadius = '12px';
            limitBadge.style.fontSize = '12px';
            headerEl.appendChild(limitBadge);
        }
        
        if (onColumnClick) {
            headerEl.style.cursor = 'pointer';
            headerEl.addEventListener('click', function() {
                if (window.__s14_emit_action) {
                    window.__s14_emit_action(onColumnClick, { columnId: column.id });
                }
            });
        }
        
        colEl.appendChild(headerEl);
        
        // Cards container
        const cardsContainer = document.createElement('div');
        cardsContainer.className = 'kanban-cards-container';
        cardsContainer.dataset.columnId = column.id;
        cardsContainer.style.display = 'flex';
        cardsContainer.style.flexDirection = 'column';
        cardsContainer.style.gap = '8px';
        cardsContainer.style.minHeight = '100px';
        
        // Filter cards for this column
        const columnCards = cards.filter(c => c.columnId === column.id);
        
        columnCards.forEach(card => {
            const cardEl = document.createElement('div');
            cardEl.className = 'kanban-card';
            cardEl.dataset.cardId = card.id;
            cardEl.style.background = 'white';
            cardEl.style.borderRadius = '6px';
            cardEl.style.padding = '12px';
            cardEl.style.boxShadow = '0 1px 3px rgba(0,0,0,0.1)';
            cardEl.style.border = '1px solid #e9ecef';
            cardEl.style.transition = 'all 0.2s';
            
            // Card title
            const titleEl = document.createElement('div');
            titleEl.className = 'kanban-card-title';
            titleEl.textContent = card.title;
            titleEl.style.fontWeight = '500';
            titleEl.style.fontSize = '14px';
            titleEl.style.marginBottom = '6px';
            cardEl.appendChild(titleEl);
            
            // Card description
            if (card.description) {
                const descEl = document.createElement('div');
                descEl.className = 'kanban-card-description';
                descEl.textContent = card.description;
                descEl.style.fontSize = '12px';
                descEl.style.color = '#6c757d';
                descEl.style.marginBottom = '8px';
                cardEl.appendChild(descEl);
            }
            
            // Card metadata row
            const metaEl = document.createElement('div');
            metaEl.className = 'kanban-card-meta';
            metaEl.style.display = 'flex';
            metaEl.style.flexWrap = 'wrap';
            metaEl.style.gap = '6px';
            metaEl.style.fontSize = '11px';
            metaEl.style.color = '#6c757d';
            
            if (card.assignee) {
                const assigneeEl = document.createElement('span');
                assigneeEl.className = 'kanban-card-assignee';
                assigneeEl.textContent = '👤 ' + card.assignee;
                assigneeEl.style.background = '#f1f3f5';
                assigneeEl.style.padding = '2px 8px';
                assigneeEl.style.borderRadius = '4px';
                metaEl.appendChild(assigneeEl);
            }
            
            if (card.priority) {
                const priorityEl = document.createElement('span');
                priorityEl.className = 'kanban-card-priority ' + card.priority;
                var priorityMap = {
                    'low': '🟢 Low',
                    'medium': '🟡 Medium',
                    'high': '🟠 High',
                    'critical': '🔴 Critical'
                };
                priorityEl.textContent = priorityMap[card.priority] || card.priority;
                priorityEl.style.padding = '2px 8px';
                priorityEl.style.borderRadius = '4px';
                if (card.priority === 'critical') {
                    priorityEl.style.background = '#fff5f5';
                } else if (card.priority === 'high') {
                    priorityEl.style.background = '#fff4e6';
                } else if (card.priority === 'medium') {
                    priorityEl.style.background = '#fff9db';
                } else {
                    priorityEl.style.background = '#f1f3f5';
                }
                metaEl.appendChild(priorityEl);
            }
            
            if (card.dueDate) {
                const dueEl = document.createElement('span');
                dueEl.className = 'kanban-card-due';
                dueEl.textContent = '📅 ' + card.dueDate;
                dueEl.style.padding = '2px 8px';
                dueEl.style.borderRadius = '4px';
                dueEl.style.background = '#f1f3f5';
                metaEl.appendChild(dueEl);
            }
            
            // Labels
            if (card.labels && card.labels.length > 0) {
                const labelsEl = document.createElement('div');
                labelsEl.className = 'kanban-card-labels';
                labelsEl.style.display = 'flex';
                labelsEl.style.gap = '4px';
                labelsEl.style.flexWrap = 'wrap';
                labelsEl.style.marginTop = '4px';
                card.labels.forEach(function(label) {
                    const labelEl = document.createElement('span');
                    labelEl.className = 'kanban-label';
                    labelEl.textContent = label;
                    labelEl.style.background = '#e7f5ff';
                    labelEl.style.color = '#1c7ed6';
                    labelEl.style.padding = '1px 8px';
                    labelEl.style.borderRadius = '12px';
                    labelEl.style.fontSize = '10px';
                    labelsEl.appendChild(labelEl);
                });
                metaEl.appendChild(labelsEl);
            }
            
            cardEl.appendChild(metaEl);
            
            // Click handler
            if (onCardClick) {
                cardEl.style.cursor = 'pointer';
                cardEl.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (window.__s14_emit_action) {
                        window.__s14_emit_action(onCardClick, { cardId: card.id });
                    }
                });
            }
            
            // Drag and drop support
            cardEl.draggable = true;
            cardEl.addEventListener('dragstart', function(e) {
                e.dataTransfer.setData('text/plain', JSON.stringify({
                    cardId: card.id,
                    fromColumnId: column.id
                }));
                cardEl.style.opacity = '0.5';
            });
            
            cardEl.addEventListener('dragend', function() {
                cardEl.style.opacity = '1';
            });
            
            cardsContainer.appendChild(cardEl);
        });
        
        colEl.appendChild(cardsContainer);
        
        // Drop zone
        colEl.addEventListener('dragover', function(e) {
            e.preventDefault();
            colEl.style.background = '#e9ecef';
            colEl.style.borderColor = '#adb5bd';
        });
        
        colEl.addEventListener('dragleave', function() {
            colEl.style.background = '#f8f9fa';
            colEl.style.borderColor = '#e9ecef';
        });
        
        colEl.addEventListener('drop', function(e) {
            e.preventDefault();
            colEl.style.background = '#f8f9fa';
            colEl.style.borderColor = '#e9ecef';
            
            try {
                var data = JSON.parse(e.dataTransfer.getData('text/plain'));
                var toColumnId = column.id;
                
                if (data.fromColumnId !== toColumnId && onCardMove) {
                    if (window.__s14_emit_action) {
                        window.__s14_emit_action(onCardMove, {
                            cardId: data.cardId,
                            fromColumnId: data.fromColumnId,
                            toColumnId: toColumnId
                        });
                    }
                }
            } catch (err) {
                console.warn('Invalid drag data', err);
            }
        });
        
        board.appendChild(colEl);
    });
    
    container.appendChild(board);
    element.appendChild(container);
}

// Register with the framework
if (window.__s14_register_renderer) {
    window.__s14_register_renderer('KanbanBoard', renderKanbanBoard);
}
