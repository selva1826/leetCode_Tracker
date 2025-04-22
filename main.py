import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
import os
import sys
import asyncio
import base64
import io
import csv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from leetcode_total import main as run_total_scraper
from leetcode_scraper import main as run_scraper

# Ensure output directory exists
os.makedirs('./output', exist_ok=True)


def initialize_data_files():
    """Initialize or clear existing data files"""
    csv_files = ['./output/leetcode_all_users.csv', './output/leetcode_daily_activity.csv']
    for file in csv_files:
        if os.path.exists(file):
            os.remove(file)

        # Create empty files with headers
        if 'all_users' in file:
            pd.DataFrame(columns=['Username', 'Total', 'EasySolved', 'MediumSolved', 'HardSolved']).to_csv(file,
                                                                                                           index=False)
        else:
            pd.DataFrame(columns=['username', 'date', 'easy', 'medium', 'hard', 'total', 'year_range']).to_csv(file,
                                                                                                               index=False)


years = []


def is_year_in_range(year_range, target_year):
    """Check if target_year falls within the year_range."""
    try:
        start_year, end_year = map(int, year_range.split('-'))
        return start_year <= target_year <= end_year
    except ValueError:
        print(f"Invalid year range: {year_range}")
        return False


# Hardcoded credentials
VALID_USERNAME = "eecleetcode"
VALID_PASSWORD = "leetcode@eec"


def authenticate_user(username, password):
    """Validate the username and password."""
    return username == VALID_USERNAME and password == VALID_PASSWORD


def load_data():
    """Load data with error handling"""
    try:
        users_df = pd.read_csv('./output/leetcode_all_users.csv')
        activity_df = pd.read_csv('./output/leetcode_daily_activity.csv')

        # Validate dataframes have required columns
        required_user_cols = ['Username', 'Total', 'EasySolved', 'MediumSolved', 'HardSolved']
        required_activity_cols = ['username', 'date', 'easy', 'medium', 'hard', 'total', 'year_range']

        if not all(col in users_df.columns for col in required_user_cols):
            raise ValueError("User data missing required columns")

        # Handle missing columns in activity_df
        for col in required_activity_cols:
            if col not in activity_df.columns:
                print(f"Missing column in activity data: {col}. Filling with default value.")
                if col in ['easy', 'medium', 'hard', 'total']:
                    activity_df[col] = 0  # Fill numeric columns with 0
                elif col == 'year_range':
                    activity_df[col] = '2022-2026'  # Default year range
                else:
                    activity_df[col] = None  # Fill non-numeric columns with None

        return users_df, activity_df

    except Exception as e:
        print(f"Error loading data: {e}")
        # Return empty dataframes with correct structure
        users_df = pd.DataFrame(columns=['Username', 'Total', 'EasySolved', 'MediumSolved', 'HardSolved'])
        activity_df = pd.DataFrame(columns=['username', 'date', 'easy', 'medium', 'hard', 'total', 'year_range'])
        return users_df, activity_df


def save_to_excel(df, filename):
    """Save dataframe to excel file"""
    df.to_excel(f'./output/{filename}', index=False)
    return f'./output/{filename}'


# Initialize empty data files
initialize_data_files()

# Create Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
server = app.server

# Define tabs
tabs = dbc.Tabs([
    dbc.Tab(label="Leaderboard", tab_id="leaderboard"),
    dbc.Tab(label="User Performance", tab_id="user-performance"),
    dbc.Tab(label="Difficulty Analysis", tab_id="difficulty-analysis"),
    dbc.Tab(label="Activity Trends", tab_id="activity-trends"),
    dbc.Tab(label="Download Datasheet", tab_id="download-datasheet")
], id="tabs", active_tab="leaderboard")

login_layout = dbc.Container([
    dbc.Row(dbc.Col(
        html.Img(src="https://images.careerindia.com/college-photos/5858/eec-logo-finalized_1627136049.png",
                 style={"height": "100px", "margin": "auto", "display": "block"}))
    ),
    dbc.Row(dbc.Col(html.H1("Login to LeetCode Tracker", className="text-center my-4"))),
    dbc.Row(dbc.Col(
        dbc.Input(id="login-username", placeholder="Enter Username", type="text", className="mb-3")
    )),
    dbc.Row(dbc.Col(
        dbc.Input(id="login-password", placeholder="Enter Password", type="password", className="mb-3")
    )),
    dbc.Row(dbc.Col(
        dbc.Button("Login", id="login-button", color="primary", className="mt-3")
    )),
    dbc.Row(dbc.Col(
        dbc.Alert(id="login-alert", color="danger", is_open=False, duration=4000)
    ))
])

app.layout = html.Div([
    dcc.Store(id='auth-status', data=False),
    html.Div(id="page-content", children=login_layout),
    html.Div(id="tab-content"), 
    dcc.Download(id="download-leaderboard")  
])


# Callback to handle file upload
@app.callback(
    [Output('usernames-store', 'data'),
     Output('student-data-store', 'data'),
     Output('upload-status', 'children'),
     Output('upload-status', 'is_open'),
     Output('fetch-data-btn', 'disabled')],
    [Input('upload-usernames', 'contents')],
    [State('upload-usernames', 'filename')]
)
def handle_upload(contents, filename):
    if contents is None:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, True

    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)

    try:
        student_data = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        required_cols = ['Register_Number', 'Student_Name', 'username', 'Department']
        if not all(col in student_data.columns for col in required_cols):
            return dash.no_update, dash.no_update, "CSV file missing required columns: Register_Number, Student_Name, username, Department", True, True

        usernames = student_data['username'].tolist()
        if not usernames:
            return dash.no_update, dash.no_update, "No usernames found in the file", True, True

        student_data_dict = student_data.to_dict('records')
        return {'usernames': usernames}, {
            'student_data': student_data_dict}, f"Successfully loaded {len(usernames)} students", True, False

    except Exception as e:
        return dash.no_update, dash.no_update, f"Error reading file: {str(e)}", True, True


@app.callback(
    [Output('processed-data', 'data'),
     Output('data-loaded-flag', 'data'),
     Output('upload-status', 'children', allow_duplicate=True),
     Output('upload-status', 'is_open', allow_duplicate=True),
     Output('upload-status', 'color'),
     Output('loading-output', 'children')],
    [Input('fetch-data-btn', 'n_clicks')],
    [State('usernames-store', 'data'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def secure_fetch_data(n_clicks, usernames_data, auth_status):
    if not auth_status:
        raise dash.exceptions.PreventUpdate

    if n_clicks is None or usernames_data is None:
        return {'ready': False}, False, dash.no_update, dash.no_update, dash.no_update, ""

    usernames = usernames_data.get('usernames', [])
    if not usernames:
        return {'ready': False}, False, "No usernames to fetch", True, "danger", ""

    try:
        initialize_data_files()
        print("Running LeetCode total scraper...")
        run_total_scraper(usernames)
        print("Running LeetCode daily scraper...")
        asyncio.run(run_scraper(usernames, days=7, output_file="./output/leetcode_daily_activity.csv"))
        users_df, activity_df = load_data()

        if not users_df.empty and not activity_df.empty:
            processed_data = process_data(users_df, activity_df)
            return {'ready': True, 'timestamp': datetime.now().isoformat()}, True, "Data fetched and processed successfully!", True, "success", ""
        else:
            return {'ready': False}, False, "No data returned from scrapers", True, "warning", ""

    except Exception as e:
        print(f"Error in fetch_data: {e}")
        return {'ready': False}, False, f"Error fetching data: {str(e)}", True, "danger", ""

def process_data(users_df, activity_df):
    """Process the data for metrics and analysis"""
    try:
        activity_df['date'] = pd.to_datetime(activity_df['date'], errors='coerce')
        users_df['HardSolved'] = users_df['HardSolved'].fillna(0).astype(int)
        users_df['MediumSolved'] = users_df['MediumSolved'].fillna(0).astype(int)
        users_df['EasySolved'] = users_df['EasySolved'].fillna(0).astype(int)
        users_df['Total'] = users_df['Total'].fillna(0).astype(int)

        users_df = users_df.rename(columns={
            'EasySolved': 'Easy Solved',
            'MediumSolved': 'Medium Solved',
            'HardSolved': 'Hard Solved'
        })

        if 'Total' not in users_df.columns:
            users_df['Total'] = users_df['Easy Solved'] + users_df['Medium Solved'] + users_df['Hard Solved']

        difficulty_avg = users_df[['Easy Solved', 'Medium Solved', 'Hard Solved']].mean().reset_index()
        difficulty_avg.columns = ['Difficulty', 'Average Solved']

        return {'processed': True}
    except Exception as e:
        print(f"Error processing data: {e}")
        return {'processed': False, 'error': str(e)}


@app.callback(
    Output("tab-content", "children"),
    [Input("tabs", "active_tab"),
     Input("data-loaded-flag", "data"),
     Input("student-data-store", "data")]
)
def render_tab_content(active_tab, data_loaded, student_data_store):
    if not data_loaded:
        return dbc.Alert("Please upload a student data CSV file and click 'Fetch Data' to load the dashboard.",
                         color="info")

    users_df, activity_df = load_data()
    student_data = pd.DataFrame(student_data_store.get('student_data', [])).copy()

    ctx = callback_context
    if not ctx.triggered:
        return dbc.Alert("Please upload a student data CSV file and click 'Fetch Data' to load the dashboard.",
                         color="info")

    try:
        activity_df = activity_df.copy()
        users_df = users_df.copy()
        activity_df['date'] = pd.to_datetime(activity_df['date'], errors='coerce')

        for col in ['easy', 'medium', 'hard', 'total']:
            if col not in activity_df.columns:
                activity_df[col] = 0

        users_df = users_df.rename(columns={
            'EasySolved': 'Easy Solved',
            'MediumSolved': 'Medium Solved',
            'HardSolved': 'Hard Solved'
        })

        if 'Total' not in users_df.columns:
            users_df['Total'] = users_df['Easy Solved'] + users_df['Medium Solved'] + users_df['Hard Solved']

        merged_df = pd.merge(users_df, student_data, left_on='Username', right_on='username', how='left')
    except Exception as e:
        print(f"Error during data preprocessing: {e}")
        return dbc.Alert(f"Error processing data: {str(e)}", color="danger")

    current_date = datetime.now()
    if 'total' not in activity_df.columns:
        activity_df['total'] = activity_df['easy'] + activity_df['medium'] + activity_df['hard']

    def calculate_streak(username):
        user_activity = activity_df[activity_df['username'] == username].sort_values('date', ascending=False)
        if user_activity.empty:
            return {'current_streak': 0, 'longest_streak': 0, 'last_active': 'Never'}

        user_activity = user_activity[user_activity['total'] > 0]
        if user_activity.empty:
            return {'current_streak': 0, 'longest_streak': 0, 'last_active': 'Never'}

        last_active = user_activity.iloc[0]['date']
        dates = user_activity['date'].sort_values(ascending=False).dt.date
        streak = 0
        current_date_check = current_date.date()
        longest_streak = 0
        temp_streak = 0

        for date in dates:
            if date == current_date_check - timedelta(days=streak):
                streak += 1
            else:
                break

        prev_date = None
        for date in sorted(dates, reverse=True):
            if prev_date is None:
                temp_streak = 1
            else:
                if (prev_date - date).days == 1:
                    temp_streak += 1
                else:
                    longest_streak = max(longest_streak, temp_streak)
                    temp_streak = 1
            prev_date = date
        longest_streak = max(longest_streak, temp_streak)

        return {
            'current_streak': streak,
            'longest_streak': longest_streak,
            'last_active': last_active.strftime('%Y-%m-%d') if pd.notna(last_active) else 'Never'
        }

    streak_data = [calculate_streak(user) for user in users_df['Username']]
    streak_df = pd.DataFrame(streak_data)
    merged_df = pd.concat([merged_df, streak_df], axis=1)

    last_week_date = current_date - timedelta(days=7)
    last_week_activity = activity_df[activity_df['date'] >= pd.to_datetime(last_week_date)]
    last_week_growth = last_week_activity.groupby('username')['total'].sum().reset_index()
    last_week_growth.columns = ['Username', 'Last Week Growth']
    merged_df = merged_df.merge(last_week_growth, on='Username', how='left').fillna(0)

    merged_df['days_since_last_active'] = (
            current_date - pd.to_datetime(merged_df['last_active'], format='%Y-%m-%d', errors='coerce')).dt.days
    merged_df['is_inactive'] = merged_df['days_since_last_active'] > 7

    difficulty_avg = merged_df[['Easy Solved', 'Medium Solved', 'Hard Solved']].mean().reset_index()
    difficulty_avg.columns = ['Difficulty', 'Average Solved']

    departments = ['All'] + sorted(student_data['Department'].unique().tolist())

    leaderboard_content = dbc.Container([
        dbc.Row([
            dbc.Col([
                html.Label("Filter by Department:"),
                dcc.Dropdown(
                    id='leaderboard-dept-filter',
                    options=[{'label': dept, 'value': dept} for dept in departments],
                    value='All',
                    clearable=False,
                    className="mb-3"
                )
            ], width=6),
            dbc.Col([
                html.Label("Filter by Year:"),
                dcc.Dropdown(
                    id='year-filter',
                    options=[],
                    value='All',
                    clearable=False,
                    className="mb-3"
                )
            ], width=6)
        ]),
        dbc.Row([
            dbc.Col(dcc.Graph(id='top-3-chart'), width=12)
        ]),
        dbc.Row([
            dbc.Col(html.H4("Full Leaderboard", className="text-center mt-4"), width=12)
        ]),
        dbc.Row([
            dbc.Col(html.Div(id='full-leaderboard'), width=12)
        ]),
        dbc.Row([
            dbc.Col(
                dbc.Button("Download Full Leaderboard", id="download-leaderboard-btn", color="primary", className="mt-3"),
                width={"size": 6, "offset": 3}, className="text-center"
            )
        ])
    ])

    user_performance_content = dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H3("User Performance Analysis", className="text-center mb-4"),
                html.Label("Select Department:"),
                dcc.Dropdown(
                    id='performance-dept-filter',
                    options=[{'label': dept, 'value': dept} for dept in departments],
                    value='All',
                    clearable=False,
                    className="mb-3"
                ),
                html.Label("Select Student:"),
                dcc.Dropdown(
                    id='student-selector',
                    options=[],
                    clearable=False,
                    className="mb-4"
                )
            ], width=12)
        ]),
        dbc.Row([
            dbc.Col(dcc.Graph(id='user-problems-chart'), width=6),
            dbc.Col(dcc.Graph(id='user-activity-trend'), width=6)
        ]),
        dbc.Row([
            dbc.Col(html.Div(id='user-details-card'), width=12)
        ])
    ])

    difficulty_content = dbc.Container([
        dbc.Row([
            dbc.Col(html.H3("Difficulty-wise Analysis", className="text-center mb-4"), width=12)
        ]),
        dbc.Row([
            dbc.Col([
                html.Label("Filter by Department:"),
                dcc.Dropdown(
                    id='difficulty-dept-filter',
                    options=[{'label': dept, 'value': dept} for dept in departments],
                    value='All',
                    clearable=False,
                    className="mb-3"
                )
            ], width=12)
        ]),
        dbc.Row([
            dbc.Col(dcc.Graph(id='difficulty-avg-chart'), width=6),
            dbc.Col(dcc.Graph(id='difficulty-distribution'), width=6)
        ]),
        dbc.Row([
            dbc.Col(dcc.Graph(id='hard-solvers'), width=12)
        ])
    ])

    activity_trends_content = dbc.Container([
        dbc.Row([
            dbc.Col(html.H3("Activity Trends", className="text-center mb-4"), width=12)
        ]),
        dbc.Row([
            dbc.Col([
                html.Label("Filter by Department:"),
                dcc.Dropdown(
                    id='activity-dept-filter',
                    options=[{'label': dept, 'value': dept} for dept in departments],
                    value='All',
                    clearable=False,
                    className="mb-3"
                )
            ], width=12)
        ]),
        dbc.Row([
            dbc.Col(dcc.Graph(id='inactive-students-chart'), width=12)
        ])
    ])

    download_content = dbc.Container([
        dbc.Row([
            dbc.Col(html.H3("Download Department-wise Activity Data", className="text-center mb-4"), width=12)
        ]),
        dbc.Row([
            dbc.Col([
                html.Label("Select Department:"),
                dcc.Dropdown(
                    id='download-dept-filter',
                    options=[{'label': dept, 'value': dept} for dept in departments],
                    value='All',
                    clearable=False,
                    className="mb-3"
                )
            ], width=12)
        ]),
        dbc.Row([
            dbc.Col([
                dbc.Button("Download Past 7 Days Activity Data", id="download-btn", color="success",
                           className="mt-2 mr-2"),
                dbc.Button("Download Past Month Activity Data", id="download-month-btn", color="success",
                           className="mt-2"),
                html.Div(id="download-status", className="mt-3")
            ], width={"size": 6, "offset": 3}, className="text-center")
        ])
    ])

    if active_tab == "leaderboard":
        return leaderboard_content
    elif active_tab == "user-performance":
        return user_performance_content
    elif active_tab == "difficulty-analysis":
        return difficulty_content
    elif active_tab == "activity-trends":
        return activity_trends_content
    elif active_tab == "download-datasheet":
        return download_content
    return "No tab selected"


@app.callback(
    [Output('top-3-chart', 'figure'),
     Output('full-leaderboard', 'children')],
    [Input('leaderboard-dept-filter', 'value'),
     Input('year-filter', 'value')],
    [State('student-data-store', 'data')]
)
def update_leaderboard(selected_dept, selected_year, student_data_store):
    users_df, _ = load_data()
    student_data = pd.DataFrame(student_data_store.get('student_data', []))
    filtered_student_data = student_data.copy()

    if selected_dept != 'All':
        filtered_student_data = filtered_student_data[filtered_student_data['Department'] == selected_dept]

    if selected_year != 'All' and 'Year' in filtered_student_data.columns:
        filtered_student_data = filtered_student_data[filtered_student_data['Year'] == selected_year]

    filtered_usernames = filtered_student_data['username'].unique()
    merged_df = pd.merge(
        users_df[users_df['Username'].isin(filtered_usernames)],
        filtered_student_data,
        left_on='Username',
        right_on='username',
        how='left'
    )

    if merged_df.empty:
        empty_fig = go.Figure()
        empty_table = html.Div("No data available for the selected filters.")
        return empty_fig, empty_table

    merged_df = merged_df.rename(columns={
        'EasySolved': 'Easy Solved',
        'MediumSolved': 'Medium Solved',
        'HardSolved': 'Hard Solved'
    })

    top_3_fig = create_top_3_chart(merged_df)
    leaderboard_table = create_full_leaderboard(merged_df)
    return top_3_fig, leaderboard_table


def create_top_3_chart(users_df):
    if users_df.empty:
        return go.Figure()

    top_3 = users_df.sort_values('Total', ascending=False).head(3)
    if len(top_3) < 3:
        while len(top_3) < 3:
            top_3 = pd.concat([top_3, pd.DataFrame([{
                'Username': f'User {len(top_3) + 1}',
                'Student_Name': f'User {len(top_3) + 1}',
                'Total': 0
            }])])

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[top_3.iloc[0]['Student_Name']],
        y=[top_3.iloc[0]['Total']],
        name="1st Place",
        marker_color='gold',
        width=0.5
    ))
    fig.add_trace(go.Bar(
        x=[top_3.iloc[1]['Student_Name']],
        y=[top_3.iloc[1]['Total']],
        name="2nd Place",
        marker_color='silver',
        width=0.5
    ))
    fig.add_trace(go.Bar(
        x=[top_3.iloc[2]['Student_Name']],
        y=[top_3.iloc[2]['Total']],
        name="3rd Place",
        marker_color='#cd7f32',
        width=0.5
    ))

    fig.update_layout(
        title="Top 3 Performers",
        xaxis_title="Student Name",
        yaxis_title="Total Problems Solved",
        showlegend=True,
        xaxis={'categoryorder': 'array',
               'categoryarray': [top_3.iloc[1]['Student_Name'], top_3.iloc[0]['Student_Name'],
                                 top_3.iloc[2]['Student_Name']]}
    )
    return fig


@app.callback(
    Output('year-filter', 'options'),
    [Input('student-data-store', 'data')]
)
def populate_year_options(student_data_store):
    student_data = pd.DataFrame(student_data_store.get('student_data', []))
    if 'Year' not in student_data.columns:
        print("Warning: 'Year' column not found in student data")
        return [{'label': 'All', 'value': 'All'}]

    unique_years = ['All'] + sorted(student_data['Year'].unique().tolist())
    options = [{'label': year, 'value': year} for year in unique_years]
    return options


def create_full_leaderboard(users_df):
    if users_df.empty:
        return html.Div("No data available")

    leaderboard_df = users_df.sort_values('Total', ascending=False)
    table = dbc.Table(
        [
            html.Thead(
                html.Tr([
                    html.Th("Rank"),
                    html.Th("Register Number"),
                    html.Th("Student Name"),
                    html.Th("Username"),
                    html.Th("Department"),
                    html.Th("Total"),
                    html.Th("Easy"),
                    html.Th("Medium"),
                    html.Th("Hard"),
                    html.Th("Year")
                ])
            ),
            html.Tbody([
                html.Tr([
                    html.Td(i + 1),
                    html.Td(user['Register_Number']),
                    html.Td(user['Student_Name']),
                    html.Td(user['Username']),
                    html.Td(user['Department']),
                    html.Td(user['Total']),
                    html.Td(user['Easy Solved']),
                    html.Td(user['Medium Solved']),
                    html.Td(user['Hard Solved']),
                    html.Td(user['Year'])
                ]) for i, (_, user) in enumerate(leaderboard_df.iterrows())
            ])
        ],
        bordered=True,
        hover=True,
        responsive=True,
        striped=True,
    )
    return table


@app.callback(
    Output("download-leaderboard", "data"),
    [Input("download-leaderboard-btn", "n_clicks")],
    [State("leaderboard-dept-filter", "value"),
     State("year-filter", "value"),
     State("student-data-store", "data")],
    prevent_initial_call=True
)
def download_full_leaderboard(n_clicks, selected_dept, selected_year, student_data_store):
    # Load data as used in the leaderboard display
    users_df, _ = load_data()
    student_data = pd.DataFrame(student_data_store.get('student_data', []))
    filtered_student_data = student_data.copy()

    # Apply the same filters as used in the leaderboard display
    if selected_dept != 'All':
        filtered_student_data = filtered_student_data[filtered_student_data['Department'] == selected_dept]
    if selected_year != 'All' and 'Year' in filtered_student_data.columns:
        filtered_student_data = filtered_student_data[filtered_student_data['Year'] == selected_year]

    # Merge filtered student data with user data
    filtered_usernames = filtered_student_data['username'].unique()
    merged_df = pd.merge(
        users_df[users_df['Username'].isin(filtered_usernames)],
        filtered_student_data,
        left_on='Username',
        right_on='username',
        how='left'
    )

    # If no data is available, do not update
    if merged_df.empty:
        return dash.no_update

    # Rename columns to match displayed leaderboard
    merged_df = merged_df.rename(columns={
        'EasySolved': 'Easy Solved',
        'MediumSolved': 'Medium Solved',
        'HardSolved': 'Hard Solved'
    })

    # Sort data in descending order of "Total" problems solved
    merged_df = merged_df.sort_values(by='Total', ascending=False)

    # Add rank column and ensure column order matches the displayed leaderboard
    merged_df.insert(0, 'Rank', range(1, len(merged_df) + 1))
    column_order = [
        'Rank', 'Register_Number', 'Student_Name', 'Username', 'Department',
        'Total', 'Easy Solved', 'Medium Solved', 'Hard Solved', 'Year'
    ]
    merged_df = merged_df[column_order]

    # Generate the Excel file for download
    filename = "Full_Leaderboard.xlsx"
    return dcc.send_data_frame(merged_df.to_excel, filename, index=False)

    
@app.callback(
    [Output('difficulty-avg-chart', 'figure'),
     Output('difficulty-distribution', 'figure'),
     Output('hard-solvers', 'figure')],
    [Input('difficulty-dept-filter', 'value')],
    [State('student-data-store', 'data')]
)
def update_difficulty_analysis(selected_dept, student_data_store):
    users_df, _ = load_data()
    student_data = pd.DataFrame(student_data_store.get('student_data', []))
    merged_df = pd.merge(users_df, student_data, left_on='Username', right_on='username', how='left')

    if selected_dept != 'All':
        merged_df = merged_df[merged_df['Department'] == selected_dept]

    if merged_df.empty:
        empty_fig = go.Figure()
        return empty_fig, empty_fig, empty_fig

    merged_df = merged_df.rename(columns={
        'EasySolved': 'Easy Solved',
        'MediumSolved': 'Medium Solved',
        'HardSolved': 'Hard Solved'
    })

    difficulty_avg = merged_df[['Easy Solved', 'Medium Solved', 'Hard Solved']].mean().reset_index()
    difficulty_avg.columns = ['Difficulty', 'Average Solved']

    avg_chart = create_difficulty_avg_chart(difficulty_avg)
    dist_chart = create_difficulty_distribution(merged_df)
    hard_solvers_chart = create_hard_solvers_chart(merged_df)
    return avg_chart, dist_chart, hard_solvers_chart


def create_difficulty_avg_chart(difficulty_avg):
    if difficulty_avg.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=difficulty_avg['Difficulty'],
        y=difficulty_avg['Average Solved'],
        marker_color=['#00B0A1', '#FFC154', '#FF6B6B'],
        text=difficulty_avg['Average Solved'].round(1),
        textposition='auto'
    ))
    fig.update_layout(
        title='Average Problems Solved by Difficulty',
        xaxis_title='Difficulty',
        yaxis_title='Average Solved',
        showlegend=False
    )
    return fig


def create_difficulty_distribution(users_df):
    if users_df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Box(y=users_df['Easy Solved'], name='Easy', marker_color='#00B0A1'))
    fig.add_trace(go.Box(y=users_df['Medium Solved'], name='Medium', marker_color='#FFC154'))
    fig.add_trace(go.Box(y=users_df['Hard Solved'], name='Hard', marker_color='#FF6B6B'))
    fig.update_layout(
        title='Distribution of Problems Solved by Difficulty',
        yaxis_title='Problems Solved',
        boxmode='group'
    )
    return fig


def create_hard_solvers_chart(users_df):
    if users_df.empty:
        return go.Figure()

    top_hard_solvers = users_df.sort_values('Hard Solved', ascending=False).head(10)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=top_hard_solvers['Student_Name'],
        y=top_hard_solvers['Hard Solved'],
        marker_color='#FF6B6B',
        text=top_hard_solvers['Hard Solved'],
        textposition='auto'
    ))
    fig.update_layout(
        title='Top 10 Hard Problem Solvers',
        xaxis_title='Student Name',
        yaxis_title='Hard Problems Solved',
        showlegend=False
    )
    return fig


@app.callback(
    Output('student-selector', 'options'),
    [Input('performance-dept-filter', 'value')],
    [State('student-data-store', 'data')]
)
def update_student_dropdown(selected_dept, student_data_store):
    student_data = pd.DataFrame(student_data_store.get('student_data', []))
    if selected_dept != 'All':
        student_data = student_data[student_data['Department'] == selected_dept]

    options = [{'label': f"{row['Student_Name']} ({row['Register_Number']})", 'value': row['username']}
               for _, row in student_data.iterrows()]
    return options


@app.callback(
    [Output('user-problems-chart', 'figure'),
     Output('user-activity-trend', 'figure'),
     Output('user-details-card', 'children')],
    [Input('student-selector', 'value')],
    [State('student-data-store', 'data')]
)
def update_user_performance(selected_username, student_data_store):
    if not selected_username:
        empty_fig = go.Figure()
        empty_card = html.Div("Please select a student")
        return empty_fig, empty_fig, empty_card

    users_df, activity_df = load_data()
    student_data = pd.DataFrame(student_data_store.get('student_data', []))
    user_data = users_df[users_df['Username'] == selected_username]
    user_activity = activity_df[activity_df['username'] == selected_username]
    student_info = student_data[student_data['username'] == selected_username]

    if user_data.empty or student_info.empty:
        empty_fig = go.Figure()
        empty_card = html.Div("No data available for selected student")
        return empty_fig, empty_fig, empty_card

    user_data = user_data.rename(columns={
        'EasySolved': 'Easy Solved',
        'MediumSolved': 'Medium Solved',
        'HardSolved': 'Hard Solved'
    })

    problems_chart = create_user_problems_chart(user_data)
    activity_chart = create_user_activity_chart(user_activity)

    current_date = datetime.now()

    def calculate_user_streak(activity_df):
        if activity_df.empty:
            return {'current_streak': 0, 'longest_streak': 0, 'last_active': 'Never'}

        activity_df = activity_df.sort_values('date', ascending=False)
        activity_with_problems = activity_df[activity_df['total'] > 0]
        if activity_with_problems.empty:
            return {'current_streak': 0, 'longest_streak': 0, 'last_active': 'Never'}

        last_active = activity_with_problems.iloc[0]['date']
        dates = activity_with_problems['date'].sort_values(ascending=False).dt.date
        streak = 0
        current_date_check = current_date.date()
        longest_streak = 0
        temp_streak = 0

        for date in dates:
            if date == current_date_check - timedelta(days=streak):
                streak += 1
            else:
                break

        prev_date = None
        for date in sorted(dates, reverse=True):
            if prev_date is None:
                temp_streak = 1
            else:
                if (prev_date - date).days == 1:
                    temp_streak += 1
                else:
                    longest_streak = max(longest_streak, temp_streak)
                    temp_streak = 1
            prev_date = date
        longest_streak = max(longest_streak, temp_streak)

        return {
            'current_streak': streak,
            'longest_streak': longest_streak,
            'last_active': last_active.strftime('%Y-%m-%d') if pd.notna(last_active) else 'Never'
        }

    streak_info = calculate_user_streak(user_activity)
    last_week_date = current_date - timedelta(days=7)
    last_week_activity = user_activity[user_activity['date'] >= pd.to_datetime(last_week_date)]
    last_week_growth = last_week_activity['total'].sum()
    user_details_card = create_user_details_card(user_data, student_info, streak_info, last_week_growth)
    return problems_chart, activity_chart, user_details_card


def create_user_problems_chart(user_data):
    if user_data.empty:
        return go.Figure()

    categories = ['Easy Solved', 'Medium Solved', 'Hard Solved']
    values = [user_data[cat].values[0] for cat in categories]
    colors = ['#00B0A1', '#FFC154', '#FF6B6B']
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=categories,
        y=values,
        marker_color=colors,
        text=values,
        textposition='auto'
    ))
    fig.update_layout(
        title=f"Problems Solved by {user_data['Username'].values[0]}",
        xaxis_title='Difficulty',
        yaxis_title='Problems Solved',
        showlegend=False
    )
    return fig


def create_user_activity_chart(user_activity):
    if user_activity.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No Activity Data Available",
            xaxis_title="Date",
            yaxis_title="Problems Solved"
        )
        return fig

    user_activity['date'] = pd.to_datetime(user_activity['date'])
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    filtered_activity = user_activity[(user_activity['date'] >= start_date) & (user_activity['date'] <= end_date)]
    filtered_activity = filtered_activity.sort_values('date')

    if filtered_activity.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No Activity in Last 30 Days",
            xaxis_title="Date",
            yaxis_title="Problems Solved"
        )
        return fig

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=filtered_activity['date'],
        y=filtered_activity['easy'],
        name='Easy',
        mode='lines+markers',
        marker_color='#00B0A1'
    ))
    fig.add_trace(go.Scatter(
        x=filtered_activity['date'],
        y=filtered_activity['medium'],
        name='Medium',
        mode='lines+markers',
        marker_color='#FFC154'
    ))
    fig.add_trace(go.Scatter(
        x=filtered_activity['date'],
        y=filtered_activity['hard'],
        name='Hard',
        mode='lines+markers',
        marker_color='#FF6B6B'
    ))
    fig.add_trace(go.Scatter(
        x=filtered_activity['date'],
        y=filtered_activity['total'],
        name='Total',
        mode='lines+markers',
        marker_color='#746AB0',
        line=dict(width=3)
    ))
    fig.update_layout(
        title="Activity Trend (Last 30 Days)",
        xaxis_title="Date",
        yaxis_title="Problems Solved",
        showlegend=True
    )
    return fig


def create_user_details_card(user_data, student_info, streak_info, last_week_growth):
    if user_data.empty or student_info.empty:
        return html.Div("No data available")

    card = dbc.Card([
        dbc.CardHeader(html.H4(f"{student_info['Student_Name'].values[0]} - Performance Details")),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H5("Student Information"),
                    html.P(f"Register Number: {student_info['Register_Number'].values[0]}"),
                    html.P(f"Department: {student_info['Department'].values[0]}"),
                    html.P(f"LeetCode Username: {user_data['Username'].values[0]}")
                ], width=6),
                dbc.Col([
                    html.H5("LeetCode Stats"),
                    html.P(f"Total Problems: {user_data['Total'].values[0]}"),
                    html.P(f"Current Streak: {streak_info['current_streak']} days"),
                    html.P(f"Longest Streak: {streak_info['longest_streak']} days"),
                    html.P(f"Last Active: {streak_info['last_active']}"),
                    html.P(f"Problems Solved (Last 7 Days): {last_week_growth}")
                ], width=6)
            ])
        ])
    ])
    return card


@app.callback(
    [Output('inactive-students-chart', 'figure')],
    [Input('activity-dept-filter', 'value')],
    [State('student-data-store', 'data')]
)
def update_activity_trends(selected_dept, student_data_store):
    _, activity_df = load_data()
    student_data = pd.DataFrame(student_data_store.get('student_data', []))
    merged_activity = pd.merge(activity_df, student_data, left_on='username', right_on='username', how='left')

    if selected_dept != 'All':
        merged_activity = merged_activity[merged_activity['Department'] == selected_dept]

    if merged_activity.empty:
        empty_fig = go.Figure()
        return [empty_fig]

    inactive_chart = create_inactive_students_chart(merged_activity, student_data, selected_dept)
    return [inactive_chart]


def create_inactive_students_chart(activity_df, student_data, selected_dept):
    if activity_df.empty:
        return go.Figure()

    if selected_dept != 'All':
        student_data = student_data[student_data['Department'] == selected_dept].copy()

    all_usernames = set(student_data['username'].unique())
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    activity_df = activity_df.copy()
    activity_df['date'] = pd.to_datetime(activity_df['date'])
    recent_activity = activity_df[(activity_df['date'] >= start_date) & (activity_df['date'] <= end_date)]
    active_usernames = set(recent_activity[recent_activity['total'] > 0]['username'].unique())
    inactive_usernames = all_usernames - active_usernames
    active_count = len(active_usernames)
    inactive_count = len(inactive_usernames)

    fig = go.Figure(data=[go.Pie(
        labels=['Active Students', 'Inactive Students'],
        values=[active_count, inactive_count],
        hoverinfo='label+percent+value',
        textinfo='label+value+percent',
        marker=dict(colors=['#00B0A1', '#FF6B6B'])
    )])
    fig.update_layout(
        title="Active vs Inactive Students (Last 7 Days)",
        showlegend=True
    )
    return fig


@app.callback(
    Output("download-datasheet-excel", "data"),
    [Input("download-btn", "n_clicks"),
     Input("download-month-btn", "n_clicks")],
    [State("download-dept-filter", "value"),
     State("student-data-store", "data")],
    prevent_initial_call=True
)
def generate_excel(n_clicks_7days, n_clicks_month, selected_dept, student_data_store):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    student_data = pd.DataFrame(student_data_store.get('student_data', []))

    if selected_dept != 'All':
        student_data = student_data[student_data['Department'] == selected_dept].copy()

    usernames = student_data['username'].tolist()
    if not usernames:
        return dash.no_update

    if button_id == "download-btn" and n_clicks_7days:
        try:
            activity_df = pd.read_csv('./output/leetcode_daily_activity.csv')
            activity_df['date'] = pd.to_datetime(activity_df['date'])
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=6)
            date_range = pd.date_range(start=start_date, end=end_date)
            filtered_activity = activity_df[
                (activity_df['username'].isin(student_data['username'])) &
                (activity_df['date'] >= pd.Timestamp(start_date)) &
                (activity_df['date'] <= pd.Timestamp(end_date))
                ].copy()

            if not filtered_activity.empty:
                filtered_activity.loc[:, 'date_str'] = filtered_activity['date'].dt.strftime('%Y-%m-%d')
                pivot_df = filtered_activity.pivot_table(
                    index='username',
                    columns='date_str',
                    values='total',
                    aggfunc='sum',
                    fill_value=0
                ).reset_index()

                for date in date_range:
                    date_str = date.strftime('%Y-%m-%d')
                    if date_str not in pivot_df.columns:
                        pivot_df[date_str] = 0

                result_df = pd.merge(student_data[['username', 'Register_Number', 'Student_Name', 'Department']],
                                     pivot_df, on='username', how='left')
                date_cols = [date.strftime('%Y-%m-%d') for date in date_range]
                for col in date_cols:
                    if col in result_df.columns:
                        result_df[col] = result_df[col].fillna(0).astype(int)
                    else:
                        result_df[col] = 0

                ordered_cols = ['Register_Number', 'Student_Name', 'username', 'Department'] + date_cols
                result_df = result_df[ordered_cols]
            else:
                result_df = student_data[['Register_Number', 'Student_Name', 'username', 'Department']].copy()
                for date in date_range:
                    result_df[date.strftime('%Y-%m-%d')] = 0

            result_df = result_df.rename(columns={'username': 'LeetCode Username'})
            dept_name = selected_dept if selected_dept != 'All' else 'All_Departments'
            current_date = datetime.now().strftime('%Y-%m-%d')
            filename = f"LeetCode_7Day_Activity_{dept_name}_{current_date}.xlsx"
            return dcc.send_data_frame(result_df.to_excel, filename, index=False)

        except Exception as e:
            print(f"Error generating 7-day data: {e}")
            return dash.no_update

    elif button_id == "download-month-btn" and n_clicks_month:
        try:
            asyncio.run(run_scraper(usernames, days=30, output_file="./output/leetcode_past_month.csv"))
            activity_df = pd.read_csv('./output/leetcode_past_month.csv')
        except Exception as e:
            print(f"Error running past month scraper: {e}")
            activity_df = pd.DataFrame(columns=['username', 'date', 'easy', 'medium', 'hard', 'total', 'year_range'])

        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=29)
        date_range = pd.date_range(start=start_date, end=end_date)
        activity_df = activity_df.copy()
        activity_df['date'] = pd.to_datetime(activity_df['date'])

        filtered_activity = activity_df[
            (activity_df['username'].isin(student_data['username'])) &
            (activity_df['date'] >= pd.Timestamp(start_date)) &
            (activity_df['date'] <= pd.Timestamp(end_date))
            ].copy()

        if not filtered_activity.empty:
            filtered_activity.loc[:, 'date_str'] = filtered_activity['date'].dt.strftime('%Y-%m-%d')
            pivot_df = filtered_activity.pivot_table(
                index='username',
                columns='date_str',
                values='total',
                aggfunc='sum',
                fill_value=0
            ).reset_index()

            for date in date_range:
                date_str = date.strftime('%Y-%m-%d')
                if date_str not in pivot_df.columns:
                    pivot_df[date_str] = 0

            result_df = pd.merge(student_data[['username', 'Register_Number', 'Student_Name', 'Department']],
                                 pivot_df, on='username', how='left')
            date_cols = [date.strftime('%Y-%m-%d') for date in date_range]
            for col in date_cols:
                if col in result_df.columns:
                    result_df[col] = result_df[col].fillna(0).astype(int)
                else:
                    result_df[col] = 0

            ordered_cols = ['Register_Number', 'Student_Name', 'username', 'Department'] + date_cols
            result_df = result_df[ordered_cols]
        else:
            result_df = student_data[['Register_Number', 'Student_Name', 'username', 'Department']].copy()
            for date in date_range:
                result_df[date.strftime('%Y-%m-%d')] = 0

        result_df = result_df.rename(columns={'username': 'LeetCode Username'})
        dept_name = selected_dept if selected_dept != 'All' else 'All_Departments'
        current_date = datetime.now().strftime('%Y-%m-%d')
        filename = f"LeetCode_PastMonth_Activity_{dept_name}_{current_date}.xlsx"
        return dcc.send_data_frame(result_df.to_excel, filename, index=False)

    return dash.no_update


@app.callback(
    Output("download-status", "children"),
    [Input("download-btn", "n_clicks"),
     Input("download-month-btn", "n_clicks")],
    prevent_initial_call=True
)
def update_download_status(n_clicks_7days, n_clicks_month):
    ctx = dash.callback_context
    if not ctx.triggered:
        return ""

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if button_id == "download-btn" and n_clicks_7days:
        message = "7-day Excel file generated successfully! Check your downloads folder."
    elif button_id == "download-month-btn" and n_clicks_month:
        message = "Past month Excel file generated successfully! Check your downloads folder."
    else:
        return ""

    return html.Div(message, style={"color": "green", "font-weight": "bold"})


@app.callback(
    [Output('page-content', 'children'),
     Output('auth-status', 'data'),
     Output('login-alert', 'children'),
     Output('login-alert', 'is_open'),
     Output('login-alert', 'color')],
    [Input('login-button', 'n_clicks')],
    [State('login-username', 'value'),
     State('login-password', 'value')]
)
def handle_login(n_clicks, username, password):
    if n_clicks is None:
        raise dash.exceptions.PreventUpdate

    if authenticate_user(username, password):
        return (
            dbc.Container([
                dcc.Store(id='usernames-store'),
                dcc.Store(id='student-data-store'),
                dcc.Store(id='data-loaded-flag', data=False),
                dcc.Store(id='processed-data', data={'ready': False}),
                dbc.Row(dbc.Col(
                    html.Img(src="https://images.careerindia.com/college-photos/5858/eec-logo-finalized_1627136049.png",
                             style={"height": "100px", "margin": "auto", "display": "block"}))
                ),
                dbc.Row(dbc.Col(html.H1("LeetCode Dashboard", className="text-center my-4"))),
                dbc.Row([
                    dbc.Col([
                        dcc.Upload(
                            id='upload-usernames',
                            children=html.Div([
                                'Drag and Drop or ',
                                html.A('Select Student Data CSV File')
                            ]),
                            style={
                                'width': '100%',
                                'height': '60px',
                                'lineHeight': '60px',
                                'borderWidth': '1px',
                                'borderStyle': 'dashed',
                                'borderRadius': '5px',
                                'textAlign': 'center',
                                'margin': '10px'
                            },
                            multiple=False
                        ),
                        dbc.Button("Fetch Data", id="fetch-data-btn", color="primary", className="mt-2", disabled=True),
                        dbc.Alert(id='upload-status', color="info", is_open=False, duration=4000),
                        dcc.Loading(
                            id="loading-fetch",
                            type="default",
                            children=html.Div(id="loading-output")
                        )
                    ], width=12)
                ]),
                dbc.Row(dbc.Col(tabs)),
                html.Div(id="tab-content"),
                dcc.Download(id="download-datasheet-excel")
            ]),
            True,
            "Login successful!", True, "success"
        )
    else:
        return login_layout, False, "Invalid username or password.", True, "danger"


if __name__ == '__main__':
    app.run(debug=True)
