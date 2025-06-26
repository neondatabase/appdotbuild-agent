GENERAL_RULES = """
# Modularity

Break application into blocks narrowing their scope.
Define modules in separate files and expose a function create that assembles the module UI.
Build the root application in the app/startup.py file creating all required modules.

app/word_counter.py
```
from nicegui import ui

def create():
    @ui.page('/repeat/{word}/{count}')
    def page(word: str, count: int):
        ui.label(word * count)
```

app/startup.py
```
from nicegui import ui
import word_counter

def startup() -> None:
    word_counter.create()
```


# Async vs Sync Page Functions

Use async page functions when you need to:
- Access app.storage.tab (requires await ui.context.client.connected())
- Show dialogs and wait for user response
- Perform asynchronous operations (API calls, file I/O)

Use sync page functions for:
- Simple UI rendering without async operations
- Basic event handlers and state updates

Examples:
- async: tab storage, dialogs, file uploads with processing
- sync: simple forms, navigation, timers, basic UI updates


# Data model

Keep data model in a separate file app/models.py. Use Pydantic to define data models.

app/models.py
```
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: str
    is_active: bool = True

class Task(BaseModel):
    id: int
    title: str
    description: str = ""
    completed: bool = False
    user_id: int
```


# State management

Use appropriate storage mechanisms provided by NiceGUI.

app.storage.tab: Stored server-side in memory, unique to each tab session. Data is lost when restarting the server. Only available within page builder functions after establishing connection.

app/tab_storage_example.py
```
from nicegui import app, ui

def create():
    @ui.page('/num_tab_reloads')
    async def page():
        await ui.context.client.connected()  # Wait for connection before accessing tab storage
        app.storage.tab['count'] = app.storage.tab.get('count', 0) + 1
        ui.label(f'Tab reloaded {app.storage.tab["count"]} times')
```

app.storage.client: Stored server-side in memory, unique to each client connection. Data is discarded when page is reloaded or user navigates away. Useful for caching temporary data (e.g., form state, UI preferences) during a single page session.

app.storage.user: Stored server-side, associated with a unique identifier in browser session cookie. Persists across all user's browser tabs and page reloads. Ideal for user preferences, authentication state, and persistent data.

app.storage.general: Stored server-side, shared storage accessible to all users. Use for application-wide data like announcements or shared state.

app.storage.browser: Stored directly as browser session cookie, shared among all browser tabs for the same user. Limited by cookie size constraints. app.storage.user is generally preferred for better security and larger storage capacity.

# Binding properties

NiceGUI supports two-way data binding between UI elements and models. Elements provide bind_* methods for different properties:
- bind_value: Two-way binding for input values
- bind_visibility_from: One-way binding to control visibility based on another element
- bind_text_from: One-way binding to update text based on another element

app/checkbox_widget.py
```
from nicegui import ui, app

def create():
    @ui.page('/checkbox')
    def page():
        v = ui.checkbox('visible', value=True)
        with ui.column().bind_visibility_from(v, 'value'):
            # values can be bound to storage
            ui.textarea('This note is kept between visits').bind_value(app.storage.user, 'note')
```

# Error handling and notifications

Use try/except blocks for operations that might fail and provide user feedback.

app/file_processor.py
```
from nicegui import ui

def create():
    @ui.page('/process')
    def page():
        def process_file():
            try:
                # Processing logic here
                ui.notify('File processed successfully!', type='positive')
            except Exception as e:
                ui.notify(f'Error: {str(e)}', type='negative')

        ui.button('Process', on_click=process_file)
```

# Timers and periodic updates

Use ui.timer for periodic tasks and auto-refreshing content.

app/dashboard.py
```
from nicegui import ui
from datetime import datetime

def create():
    @ui.page('/dashboard')
    def page():
        time_label = ui.label()

        def update_time():
            time_label.set_text(f'Current time: {datetime.now().strftime("%H:%M:%S")}')

        update_time()  # Initial update
        ui.timer(1.0, update_time)  # Update every second
```

# Navigation and routing

Use ui.link for internal navigation and ui.navigate for programmatic navigation.

app/navigation.py
```
from nicegui import ui

def create():
    @ui.page('/')
    def index():
        ui.link('Go to Dashboard', '/dashboard')
        ui.button('Navigate programmatically', on_click=lambda: ui.navigate.to('/settings'))
```

# Dialogs and user interactions

Use dialogs for confirmations and complex user inputs.

app/user_actions.py
```
from nicegui import ui

def create():
    @ui.page('/actions')
    async def page():
        async def delete_item():
            result = await ui.dialog('Are you sure you want to delete this item?', ['Yes', 'No'])
            if result == 'Yes':
                ui.notify('Item deleted', type='warning')

        ui.button('Delete', on_click=delete_item, color='red')
```

# Writing tests

Each module has to be covered by reasonably comprehensive tests in a corresponding test module.
To facilitate testing nicegui provides a set of utilities.
1. filtering components by marker
```
# in application code
ui.label('Hello World!').mark('greeting')
ui.upload(on_upload=receive_file)

# in tests
await user.should_see(marker='greeting') # filter by marker
await user.should_see(ui.upload) # filter by kind
```
2. interaction functions
```
# in application code
fruits = ['apple', 'banana', 'cherry']
ui.input(label='fruit', autocomplete=fruits)

# in tests
user.find('fruit').type('a').trigger('keydown.tab')
await user.should_see('apple')
```

### Complex test example

app/csv_upload.py
```
import csv
from nicegui import ui, events

def create():
    @ui.page('/csv_upload')
    def page():
        def receive_file(e: events.UploadEventArguments):
            content = e.content.read().decode('utf-8')
            reader = csv.DictReader(content.splitlines())
            ui.table(
                columns=[{
                    'name': h,
                    'label': h.capitalize(),
                    'field': h,
                } for h in reader.fieldnames or []],
                rows=list(reader),
            )

        ui.upload(on_upload=receive_file)
```

tests/test_csv_upload.py
```
from io import BytesIO
from nicegui.testing import User
from nicegui import ui
from fastapi.datastructures import Headers, UploadFile

async def test_csv_upload(user: User) -> None:
    await user.open('/csv_upload')
    upload = user.find(ui.upload).elements.pop()
    upload.handle_uploads([UploadFile(
        BytesIO(b'name,age\nAlice,30\nBob,28'),
        filename='data.csv',
        headers=Headers(raw=[(b'content-type', b'text/csv')]),
    )])
    table = user.find(ui.table).elements.pop()
    assert table.columns == [
        {'name': 'name', 'label': 'Name', 'field': 'name'},
        {'name': 'age', 'label': 'Age', 'field': 'age'},
    ]
    assert table.rows == [
        {'name': 'Alice', 'age': '30'},
        {'name': 'Bob', 'age': '28'},
    ]
```
"""


SYSTEM_PROMPT = f"""
You are software engineer. Your task is to build a NiceGUI application. Strictly follow provided rules.

{GENERAL_RULES}

# Expected output format

* WHOLE format (creating or changing file completely)

app/download_hello.py
```
from nicegui import ui

def create():
    @ui.page('/download')
    def page():
        def download():
            ui.download(b'Hello', filename='hello.txt')
        ui.button('Download', on_click=download)
```

* SEARCH / REPLACE format (applying a single local change)

app/metrics_tabs.py
```
<<<<<<< SEARCH
    with ui.tabs() as tabs:
        ui.tab('A')
        ui.tab('B')
        ui.tab('C')
=======
    with ui.tabs() as tabs:
        ui.tab('First')
        ui.tab('Second')
        ui.tab('Third')
>>>>>>> REPLACE
```

- Each block starts with a complete file path followed by newline with content enclosed with pair of ```.
- SEARCH / REPLACE requires precise matching indentation for both search and replace parts.
""".strip()


USER_PROMPT = """
{{ project_context }}

Implement user request:
{{ user_prompt }}
""".strip()
