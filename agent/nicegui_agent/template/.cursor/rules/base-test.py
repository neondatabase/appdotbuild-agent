import pytest
from datetime import datetime, timedelta, date
from decimal import Decimal
from io import BytesIO
from sqlmodel import Session, select, func
from nicegui.testing import User
from nicegui import ui
from fastapi.datastructures import Headers, UploadFile
from app.database import reset_db, get_session
from app.models import User as UserModel, Project, Task, TaskCreate, Comment
from app.task_service import calculate_project_stats, get_overdue_tasks, assign_task

# Fixtures
@pytest.fixture()
def clean_db():
    """Reset database before and after test."""
    reset_db()
    yield
    reset_db()

@pytest.fixture()
def sample_data(clean_db):
    """Create sample data for tests."""
    with Session(get_session()) as session:
        # Create users
        alice = UserModel(
            username="alice",
            email="alice@example.com",
            full_name="Alice Johnson"
        )
        bob = UserModel(
            username="bob",
            email="bob@example.com",
            full_name="Bob Smith",
            is_active=False
        )
        session.add_all([alice, bob])
        session.commit()
        session.refresh(alice)
        session.refresh(bob)
        
        # Create project
        project = Project(
            name="Test Project",
            description="A test project for unit tests",
            owner_id=alice.id,
            budget=Decimal('10000.00'),
            tags=["test", "demo"]
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        
        # Create tasks
        task1 = Task(
            title="Completed Task",
            project_id=project.id,
            assignee_id=alice.id,
            priority=3,
            completed=True,
            completed_at=datetime.utcnow()
        )
        
        task2 = Task(
            title="Overdue Task",
            project_id=project.id,
            assignee_id=bob.id,
            priority=5,
            due_date=datetime.utcnow() - timedelta(days=1)
        )
        
        task3 = Task(
            title="Future Task",
            description="Task with future due date",
            project_id=project.id,
            priority=1,
            due_date=datetime.utcnow() + timedelta(days=7)
        )
        
        session.add_all([task1, task2, task3])
        session.commit()
        
        return {
            'users': {'alice': alice, 'bob': bob},
            'project': project,
            'tasks': [task1, task2, task3]
        }

# Logic-focused tests (majority of test suite)

def test_calculate_project_stats(sample_data):
    """Test project statistics calculation."""
    project = sample_data['project']
    
    stats = calculate_project_stats(project.id)
    
    assert stats['total_tasks'] == 3
    assert stats['completed_tasks'] == 1
    assert stats['overdue_tasks'] == 1
    assert stats['completion_rate'] == Decimal('33.33')
    assert isinstance(stats['completion_rate'], Decimal)

def test_calculate_project_stats_empty_project(clean_db):
    """Test statistics for project with no tasks."""
    with Session(get_session()) as session:
        user = UserModel(username="test", email="test@example.com", full_name="Test User")
        session.add(user)
        session.commit()
        session.refresh(user)
        
        project = Project(name="Empty Project", owner_id=user.id)
        session.add(project)
        session.commit()
        session.refresh(project)
    
    stats = calculate_project_stats(project.id)
    
    assert stats['total_tasks'] == 0
    assert stats['completed_tasks'] == 0
    assert stats['overdue_tasks'] == 0
    assert stats['completion_rate'] == Decimal('0')

def test_calculate_project_stats_nonexistent_project():
    """Test statistics for non-existent project."""
    stats = calculate_project_stats(9999)
    assert stats is None

def test_get_overdue_tasks(sample_data):
    """Test retrieving overdue tasks."""
    overdue = get_overdue_tasks()
    
    assert len(overdue) == 1
    assert overdue[0].title == "Overdue Task"
    assert overdue[0].assignee.username == "bob"
    assert not overdue[0].completed

def test_get_overdue_tasks_excludes_completed(sample_data):
    """Test that completed tasks are not included in overdue."""
    # Mark the overdue task as completed
    with Session(get_session()) as session:
        task = session.exec(
            select(Task).where(Task.title == "Overdue Task")
        ).first()
        if task:
            task.completed = True
            task.completed_at = datetime.utcnow()
            session.commit()
    
    overdue = get_overdue_tasks()
    assert len(overdue) == 0

def test_assign_task_success(sample_data):
    """Test successful task assignment."""
    task = sample_data['tasks'][2]  # Future Task (unassigned)
    alice = sample_data['users']['alice']
    
    result = assign_task(task.id, alice.id)
    
    assert result is not None
    assert result.assignee_id == alice.id
    
    # Verify in database
    with Session(get_session()) as session:
        updated_task = session.get(Task, task.id)
        assert updated_task.assignee_id == alice.id

def test_assign_task_invalid_user(sample_data):
    """Test task assignment with invalid user."""
    task = sample_data['tasks'][2]
    
    result = assign_task(task.id, 9999)
    assert result is None

def test_assign_task_invalid_task(sample_data):
    """Test task assignment with invalid task."""
    alice = sample_data['users']['alice']
    
    result = assign_task(9999, alice.id)
    assert result is None

def test_assign_task_to_inactive_user(sample_data):
    """Test that inactive users cannot be assigned tasks."""
    task = sample_data['tasks'][2]
    bob = sample_data['users']['bob']  # Bob is inactive
    
    result = assign_task(task.id, bob.id)
    assert result is None

def test_task_priority_validation():
    """Test task priority constraints."""
    task_valid = TaskCreate(
        title="Valid Priority",
        project_id=1,
        priority=3
    )
    assert 0 <= task_valid.priority <= 5
    
    # Test invalid priorities are rejected by Pydantic
    with pytest.raises(ValueError):
        TaskCreate(
            title="Invalid Priority",
            project_id=1,
            priority=6
        )

def test_none_handling_in_task_description(clean_db):
    """Test proper None handling for optional fields."""
    with Session(get_session()) as session:
        # Create prerequisites
        user = UserModel(username="test", email="test@test.com", full_name="Test")
        session.add(user)
        session.commit()
        session.refresh(user)
        
        project = Project(name="Test", owner_id=user.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        
        # Task with None description
        task1 = Task(title="No Description", project_id=project.id, description=None)
        # Task with empty string description
        task2 = Task(title="Empty Description", project_id=project.id, description="")
        
        session.add_all([task1, task2])
        session.commit()
    
    # Verify storage
    with Session(get_session()) as session:
        tasks = list(session.exec(select(Task)).all())
        
        no_desc_task = next(t for t in tasks if t.title == "No Description")
        assert no_desc_task.description is None
        
        empty_desc_task = next(t for t in tasks if t.title == "Empty Description")
        assert empty_desc_task.description == ""

def test_date_serialization(sample_data):
    """Test proper date handling and serialization."""
    task = sample_data['tasks'][1]  # Overdue task
    
    # Test date comparison
    assert task.due_date < datetime.utcnow()
    
    # Test serialization
    serialized = {
        'id': task.id,
        'title': task.title,
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'created_at': task.created_at.isoformat()
    }
    
    assert isinstance(serialized['due_date'], str)
    assert isinstance(serialized['created_at'], str)

def test_decimal_handling(sample_data):
    """Test Decimal field operations."""
    project = sample_data['project']
    
    # Test arithmetic with Decimal
    expense = Decimal('2500.50')
    remaining = project.budget - expense
    
    assert remaining == Decimal('7499.50')
    assert isinstance(remaining, Decimal)
    
    # Test comparison
    assert project.budget > Decimal('5000')
    assert project.budget < Decimal('15000')

def test_json_field_handling(sample_data):
    """Test JSON field storage and retrieval."""
    project = sample_data['project']
    
    # Verify tags
    assert isinstance(project.tags, list)
    assert "test" in project.tags
    assert len(project.tags) == 2
    
    # Update metadata
    with Session(get_session()) as session:
        p = session.get(Project, project.id)
        p.metadata = {
            'version': '1.0',
            'features': ['task-management', 'reporting'],
            'config': {'theme': 'dark', 'notifications': True}
        }
        session.commit()
    
    # Verify complex JSON storage
    with Session(get_session()) as session:
        p = session.get(Project, project.id)
        assert p.metadata['version'] == '1.0'
        assert len(p.metadata['features']) == 2
        assert p.metadata['config']['theme'] == 'dark'

def test_query_with_aggregation(sample_data):
    """Test complex queries with aggregation."""
    with Session(get_session()) as session:
        # Count tasks per priority
        result = session.exec(
            select(Task.priority, func.count(Task.id))
            .group_by(Task.priority)
            .order_by(Task.priority)
        ).all()
        
        priority_counts = dict(result)
        assert priority_counts[1] == 1  # One priority 1 task
        assert priority_counts[3] == 1  # One priority 3 task
        assert priority_counts[5] == 1  # One priority 5 task

# UI smoke tests (minority of test suite)

async def test_task_list_page_loads(user: User, sample_data):
    """Test that task list page loads and displays tasks."""
    await user.open('/tasks')
    
    # Page should load
    await user.should_see('Task Management')
    
    # Should see task titles
    await user.should_see('Completed Task')
    await user.should_see('Overdue Task')
    await user.should_see('Future Task')

async def test_create_task_dialog(user: User, sample_data):
    """Test task creation through UI."""
    await user.open('/tasks')
    
    # Click new task button
    user.find('New Task').click()
    
    # Dialog should appear
    await user.should_see('Create New Task')
    
    # Fill form
    user.find('Title').type('UI Test Task')
    user.find('Description').type('Created through UI test')
    
    # Test that selects have options
    project_select = list(user.find(ui.select, label='Project').elements)[0]
    assert len(project_select.options) > 0

async def test_task_filtering(user: User, sample_data):
    """Test task filtering functionality."""
    await user.open('/tasks')
    
    # Change filter to completed
    filter_select = list(user.find(ui.select, label='Filter').elements)[0]
    filter_select.set_value('completed')
    
    # Should only see completed task
    await user.should_see('Completed Task')
    await user.should_not_see('Overdue Task')

async def test_task_detail_navigation(user: User, sample_data):
    """Test navigation to task detail page."""
    task = sample_data['tasks'][0]
    
    await user.open(f'/tasks/{task.id}')
    
    # Should see task details
    await user.should_see(task.title)
    await user.should_see('Status:')
    await user.should_see('Priority:')
    await user.should_see('Back to tasks')

async def test_file_upload_handling(user: User):
    """Test file upload with CSV processing."""
    await user.open('/csv_upload')
    
    # Find upload element
    upload = user.find(ui.upload).elements.pop()
    
    # Create test CSV file
    csv_content = b'task,priority,status\nTest Task 1,3,pending\nTest Task 2,5,completed'
    
    # Handle upload
    upload.handle_uploads([UploadFile(
        BytesIO(csv_content),
        filename='tasks.csv',
        headers=Headers(raw=[(b'content-type', b'text/csv')])
    )])
    
    # Should see parsed table
    table = user.find(ui.table).elements.pop()
    assert len(table.columns) == 3
    assert table.columns[0]['name'] == 'task'
    assert len(table.rows) == 2

async def test_theme_toggle(user: User):
    """Test theme switching functionality."""
    await user.open('/tasks')
    
    # Find theme button (icon button with dark_mode or light_mode icon)
    theme_buttons = list(user.find(ui.button).elements)
    theme_button = next(
        (btn for btn in theme_buttons if btn.props.get('icon') in ['dark_mode', 'light_mode']),
        None
    )
    
    assert theme_button is not None
    initial_icon = theme_button.props.get('icon')
    
    # Click to toggle
    theme_button.click()
    
    # Icon should change
    assert theme_button.props.get('icon') != initial_icon

# Error handling tests

def test_handle_none_in_queries(clean_db):
    """Test proper None handling in database queries."""
    with Session(get_session()) as session:
        # Query that might return None
        result = session.exec(
            select(func.max(Task.priority))
            .where(Task.completed == True)
        ).first()
        
        # Handle None result
        max_priority = result if result is not None else 0
        assert max_priority == 0

def test_foreign_key_validation(sample_data):
    """Test foreign key constraint handling."""
    with Session(get_session()) as session:
        # Try to create task with invalid project_id
        task = Task(
            title="Invalid Project Task",
            project_id=9999,  # Non-existent project
            priority=2
        )
        
        session.add(task)
        
        # Should raise integrity error
        with pytest.raises(Exception) as exc_info:
            session.commit()
        
        assert "foreign key" in str(exc_info.value).lower()

def test_empty_query_results():
    """Test handling of empty query results."""
    with Session(get_session()) as session:
        # Query that returns no results
        users = list(session.exec(
            select(UserModel).where(UserModel.username == "nonexistent")
        ).all())
        
        assert users == []
        assert len(users) == 0
        
        # First on empty result
        user = session.exec(
            select(UserModel).where(UserModel.username == "nonexistent")
        ).first()
        
        assert user is None