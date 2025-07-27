from nicegui import app, ui, events
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select, desc, func, and_, or_
from app.database import get_session, ENGINE
from app.models import Task, TaskCreate, TaskUpdate, User, Project

def create():
    """Create the task management module with all NiceGUI patterns."""
    
    @ui.page('/tasks')
    async def tasks_page():
        """Main tasks page demonstrating various NiceGUI patterns."""
        # Wait for client connection before accessing tab storage
        await ui.context.client.connected()
        
        # Initialize tab storage
        app.storage.tab['filter'] = app.storage.tab.get('filter', 'all')
        app.storage.tab['sort_by'] = app.storage.tab.get('sort_by', 'created_at')
        
        # User preferences from persistent storage
        theme = app.storage.user.get('theme', 'light')
        
        # State variables
        tasks: List[Task] = []
        current_task: Optional[Task] = None
        
        # Helper functions
        def load_tasks():
            """Load tasks from database with proper error handling."""
            try:
                with Session(ENGINE) as session:
                    query = select(Task).join(Project).join(User, Task.assignee_id == User.id, isouter=True)
                    
                    # Apply filters based on tab storage
                    filter_value = app.storage.tab.get('filter', 'all')
                    if filter_value == 'completed':
                        query = query.where(Task.completed == True)
                    elif filter_value == 'pending':
                        query = query.where(Task.completed == False)
                    elif filter_value == 'overdue':
                        query = query.where(
                            and_(
                                Task.completed == False,
                                Task.due_date < datetime.utcnow()
                            )
                        )
                    
                    # Apply sorting
                    sort_by = app.storage.tab.get('sort_by', 'created_at')
                    if sort_by == 'priority':
                        query = query.order_by(desc(Task.priority))
                    elif sort_by == 'due_date':
                        query = query.order_by(Task.due_date.asc())
                    else:
                        query = query.order_by(desc(Task.created_at))
                    
                    # Execute query and convert to list
                    result = session.exec(query).all()
                    return list(result) if result else []
            except Exception as e:
                ui.notify(f'Error loading tasks: {str(e)}', type='negative')
                return []
        
        def refresh_tasks():
            """Refresh the task list and update UI."""
            nonlocal tasks
            tasks = load_tasks()
            task_container.refresh()
        
        async def create_task():
            """Create a new task with dialog."""
            # Create task dialog
            with ui.dialog() as dialog, ui.card():
                ui.label('Create New Task').classes('text-h6')
                
                # Form inputs with proper typing
                title_input = ui.input('Title', validation={'Required': lambda v: len(v) > 0})
                description_input = ui.textarea('Description').classes('w-full')
                
                # Project selection with None handling
                with Session(ENGINE) as session:
                    projects = list(session.exec(select(Project)).all())
                    project_options = {p.id: p.name for p in projects}
                
                project_select = ui.select(
                    label='Project',
                    options=project_options,
                    value=projects[0].id if projects else None
                ).classes('w-full')
                
                # Assignee selection with optional handling
                with Session(ENGINE) as session:
                    users = list(session.exec(select(User)).all())
                    user_options = {u.id: u.full_name for u in users}
                    user_options[None] = 'Unassigned'
                
                assignee_select = ui.select(
                    label='Assignee',
                    options=user_options,
                    value=None,
                    clearable=True
                ).classes('w-full')
                
                # Priority slider
                priority_slider = ui.slider(min=0, max=5, value=1, step=1).props('label-always')
                ui.label('Priority').classes('text-sm')
                
                # Due date with proper handling
                due_date_input = ui.date(value=None).classes('w-full')
                
                # Action buttons
                with ui.row():
                    ui.button('Cancel', on_click=lambda: dialog.submit(None))
                    ui.button('Create', color='primary', on_click=lambda: dialog.submit({
                        'title': title_input.value,
                        'description': description_input.value or None,
                        'project_id': project_select.value,
                        'assignee_id': assignee_select.value,
                        'priority': int(priority_slider.value),
                        'due_date': datetime.fromisoformat(due_date_input.value) if due_date_input.value else None
                    }))
            
            # Wait for dialog result
            result = await dialog
            
            if result:
                try:
                    # Create task in database
                    with Session(ENGINE) as session:
                        # Validate foreign keys exist
                        project = session.get(Project, result['project_id'])
                        if not project:
                            raise ValueError('Invalid project selected')
                        
                        if result['assignee_id']:
                            assignee = session.get(User, result['assignee_id'])
                            if not assignee:
                                raise ValueError('Invalid assignee selected')
                        
                        # Create task
                        task = Task(**result)
                        session.add(task)
                        session.commit()
                    
                    ui.notify('Task created successfully!', type='positive')
                    refresh_tasks()
                except Exception as e:
                    ui.notify(f'Error creating task: {str(e)}', type='negative')
        
        async def edit_task(task_id: int):
            """Edit existing task with proper None handling."""
            nonlocal current_task
            
            # Load task with relationships
            with Session(ENGINE) as session:
                task = session.get(Task, task_id)
                if not task:
                    ui.notify('Task not found', type='negative')
                    return
                current_task = task
            
            # Create edit dialog
            with ui.dialog() as dialog, ui.card():
                ui.label('Edit Task').classes('text-h6')
                
                # Pre-populate form
                title_input = ui.input('Title', value=task.title)
                description_input = ui.textarea('Description', value=task.description or '')
                
                # Completed checkbox
                completed_checkbox = ui.checkbox('Completed', value=task.completed)
                
                # Priority slider
                priority_slider = ui.slider(
                    min=0, max=5, 
                    value=task.priority, 
                    step=1
                ).props('label-always')
                
                # Due date handling
                due_date_input = ui.date(
                    value=task.due_date.date().isoformat() if task.due_date else None
                )
                
                with ui.row():
                    ui.button('Cancel', on_click=lambda: dialog.submit(None))
                    ui.button('Save', color='primary', on_click=lambda: dialog.submit({
                        'title': title_input.value,
                        'description': description_input.value or None,
                        'completed': completed_checkbox.value,
                        'priority': int(priority_slider.value),
                        'due_date': datetime.fromisoformat(due_date_input.value) if due_date_input.value else None
                    }))
            
            result = await dialog
            
            if result:
                try:
                    with Session(ENGINE) as session:
                        task = session.get(Task, task_id)
                        if task:
                            for key, value in result.items():
                                setattr(task, key, value)
                            if result['completed'] and not task.completed_at:
                                task.completed_at = datetime.utcnow()
                            session.commit()
                    
                    ui.notify('Task updated successfully!', type='positive')
                    refresh_tasks()
                except Exception as e:
                    ui.notify(f'Error updating task: {str(e)}', type='negative')
        
        def delete_task(task_id: int):
            """Delete task with confirmation."""
            # Safe lambda with None check
            async def confirm_delete():
                result = await ui.dialog('Are you sure you want to delete this task?', ['Yes', 'No'])
                if result == 'Yes':
                    try:
                        with Session(ENGINE) as session:
                            task = session.get(Task, task_id)
                            if task:
                                session.delete(task)
                                session.commit()
                                ui.notify('Task deleted', type='warning')
                                refresh_tasks()
                            else:
                                ui.notify('Task not found', type='negative')
                    except Exception as e:
                        ui.notify(f'Error deleting task: {str(e)}', type='negative')
            
            ui.timer(0.1, confirm_delete, once=True)
        
        # UI Layout
        with ui.header(elevated=True):
            with ui.row().classes('w-full items-center'):
                ui.label('Task Management').classes('text-h5')
                ui.space()
                
                # Theme toggle
                dark_mode = ui.dark_mode()
                ui.button(
                    icon='dark_mode' if theme == 'dark' else 'light_mode',
                    on_click=lambda: dark_mode.toggle()
                ).props('flat dense')
        
        with ui.column().classes('w-full p-4 gap-4'):
            # Filters and actions
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center gap-4'):
                    # Filter select with binding to tab storage
                    filter_select = ui.select(
                        label='Filter',
                        options=['all', 'pending', 'completed', 'overdue'],
                        value=app.storage.tab.get('filter', 'all')
                    ).bind_value(app.storage.tab, 'filter')
                    
                    # Sort select
                    sort_select = ui.select(
                        label='Sort by',
                        options=['created_at', 'due_date', 'priority'],
                        value=app.storage.tab.get('sort_by', 'created_at')
                    ).bind_value(app.storage.tab, 'sort_by')
                    
                    ui.space()
                    
                    # Action buttons
                    ui.button('Refresh', icon='refresh', on_click=refresh_tasks)
                    ui.button('New Task', icon='add', color='primary', on_click=create_task)
            
            # Task list container
            @ui.refreshable
            def task_container():
                if not tasks:
                    with ui.card().classes('w-full p-8 text-center'):
                        ui.label('No tasks found').classes('text-h6 text-grey')
                        ui.label('Create your first task to get started!').classes('text-grey')
                else:
                    # Task grid
                    with ui.grid(columns='1fr 1fr 1fr').classes('w-full gap-4'):
                        for task in tasks:
                            with ui.card().classes('p-4'):
                                # Task header
                                with ui.row().classes('w-full items-start'):
                                    ui.label(task.title).classes('text-h6 flex-grow')
                                    
                                    # Priority badge
                                    priority_color = ['grey', 'blue', 'green', 'yellow', 'orange', 'red'][task.priority]
                                    ui.badge(f'P{task.priority}', color=priority_color)
                                
                                # Task details
                                if task.description:
                                    ui.label(task.description).classes('text-grey-7')
                                
                                # Metadata
                                with ui.column().classes('gap-1 mt-2'):
                                    # Project
                                    with ui.row().classes('items-center gap-2'):
                                        ui.icon('folder', size='sm')
                                        ui.label(task.project.name if task.project else 'No project').classes('text-sm')
                                    
                                    # Assignee with None handling
                                    with ui.row().classes('items-center gap-2'):
                                        ui.icon('person', size='sm')
                                        assignee_name = task.assignee.full_name if task.assignee else 'Unassigned'
                                        ui.label(assignee_name).classes('text-sm')
                                    
                                    # Due date
                                    if task.due_date:
                                        with ui.row().classes('items-center gap-2'):
                                            ui.icon('event', size='sm')
                                            is_overdue = task.due_date < datetime.utcnow() and not task.completed
                                            date_class = 'text-red' if is_overdue else 'text-sm'
                                            ui.label(task.due_date.strftime('%Y-%m-%d')).classes(date_class)
                                
                                # Status
                                if task.completed:
                                    ui.chip('Completed', color='green', icon='check_circle').props('dense')
                                else:
                                    ui.chip('Pending', color='orange', icon='schedule').props('dense')
                                
                                # Actions
                                with ui.row().classes('w-full mt-3'):
                                    # Safe lambda with task_id capture
                                    ui.button(
                                        'Edit', 
                                        icon='edit',
                                        on_click=lambda e, tid=task.id: edit_task(tid) if tid else None
                                    ).props('dense flat')
                                    
                                    ui.button(
                                        'Delete', 
                                        icon='delete',
                                        color='red',
                                        on_click=lambda e, tid=task.id: delete_task(tid) if tid else None
                                    ).props('dense flat')
            
            # Initial load
            refresh_tasks()
            task_container()
            
            # Auto-refresh when filter or sort changes
            filter_select.on('update:model-value', refresh_tasks)
            sort_select.on('update:model-value', refresh_tasks)
            
            # Periodic refresh every 30 seconds
            ui.timer(30.0, refresh_tasks)
    
    @ui.page('/tasks/{task_id}')
    async def task_detail_page(task_id: int):
        """Task detail page with async operations."""
        await ui.context.client.connected()
        
        with Session(ENGINE) as session:
            task = session.get(Task, task_id)
            if not task:
                ui.label('Task not found').classes('text-h4')
                ui.link('Back to tasks', '/tasks')
                return
        
        # Display task details
        with ui.card().classes('w-full max-w-2xl mx-auto p-6'):
            ui.label(task.title).classes('text-h4')
            
            if task.description:
                ui.label(task.description).classes('text-body1 mt-2')
            
            # Task metadata grid
            with ui.grid(columns=2).classes('w-full mt-4 gap-4'):
                ui.label('Status:').classes('font-bold')
                ui.label('Completed' if task.completed else 'Pending')
                
                ui.label('Priority:').classes('font-bold') 
                ui.label(f'Level {task.priority}')
                
                ui.label('Created:').classes('font-bold')
                ui.label(task.created_at.strftime('%Y-%m-%d %H:%M'))
                
                if task.due_date:
                    ui.label('Due Date:').classes('font-bold')
                    ui.label(task.due_date.strftime('%Y-%m-%d'))
            
            ui.link('Back to tasks', '/tasks').classes('mt-4')