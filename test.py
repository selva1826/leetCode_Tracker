import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
import os
import sys
import asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from leetcode_total import main as run_total_scraper
from leetcode_daily import main as run_daily_scraper

# Ensure output directory exists
os.makedirs('./output', exist_ok=True)


def initialize_data_files():
    """Initialize or clear existing data files"""
    csv_files = ['./output/leetcode_all_users.csv', './output/leetcode_daily_activity.csv']
    for file in csv_files:
        if os.path.exists(file):
            print(f"Removing existing file: {file}")
            os.remove(file)

        # Create empty files with headers
        if 'all_users' in file:
            pd.DataFrame(columns=['Username', 'Total', 'EasySolved', 'MediumSolved', 'HardSolved']).to_csv(file,
                                                                                                           index=False)
        else:
            pd.DataFrame(columns=['username', 'date', 'easy', 'medium', 'hard', 'total']).to_csv(file, index=False)


def load_data():
    """Load data with error handling"""
    try:
        users_df = pd.read_csv('./output/leetcode_all_users.csv')
        activity_df = pd.read_csv('./output/leetcode_daily_activity.csv')

        # Validate dataframes have required columns
        required_user_cols = ['Username', 'Total', 'EasySolved', 'MediumSolved', 'HardSolved']
        required_activity_cols = ['username', 'date', 'easy', 'medium', 'hard', 'total']

        if not all(col in users_df.columns for col in required_user_cols):
            raise ValueError("User data missing required columns")

        if not all(col in activity_df.columns for col in required_activity_cols):
            raise ValueError("Activity data missing required columns")

        return users_df, activity_df

    except Exception as e:
        print(f"Error loading data: {e}")
        # Return empty dataframes with correct structure
        users_df = pd.DataFrame(columns=['Username', 'Total', 'Easy Solved', 'Medium Solved', 'Hard Solved'])
        activity_df = pd.DataFrame(columns=['username', 'date', 'easy', 'medium', 'hard', 'total'])
        return users_df, activity_df


# Initialize data files
initialize_data_files()

print("Running LeetCode total scraper...")
try:
    run_total_scraper()
except Exception as e:
    print(f"Error running total scraper: {e}")


# Load usernames
def load_usernames(filename="usernames.txt"):
    try:
        with open(filename, 'r') as file:
            return [line.strip() for line in file if line.strip()]
    except Exception as e:
        print(f"Error loading usernames: {e}")
        return []


usernames = load_usernames()

if not usernames:
    print("Warning: No usernames loaded - using empty list")
    usernames = []

print("Running LeetCode daily scraper...")
try:
    asyncio.run(run_daily_scraper(usernames))
except Exception as e:
    print(f"Error running daily scraper: {e}")

# Load the data
users_df, activity_df = load_data()

# Data preprocessing
try:
    activity_df['date'] = pd.to_datetime(activity_df['date'], errors='coerce')
    users_df['HardSolved'] = users_df['HardSolved'].fillna(0).astype(int)

    # Standardize column names
    users_df = users_df.rename(columns={
        'EasySolved': 'Easy Solved',
        'MediumSolved': 'Medium Solved',
        'HardSolved': 'Hard Solved'
    })

    # Calculate totals if not present
    if 'Total' not in users_df.columns:
        users_df['Total'] = users_df['Easy Solved'] + users_df['Medium Solved'] + users_df['Hard Solved']

    # Ensure activity data has required columns
    if 'total' not in activity_df.columns:
        activity_df['total'] = activity_df['easy'] + activity_df['medium'] + activity_df['hard']
except Exception as e:
    print(f"Error during data preprocessing: {e}")

# Calculate streaks and last active date
current_date = datetime.now()
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

    # Calculate longest streak
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


# Add streak info to users_df
streak_data = []
for user in users_df['Username']:
    streak_data.append(calculate_streak(user))

streak_df = pd.DataFrame(streak_data)
users_df = pd.concat([users_df, streak_df], axis=1)

# Calculate growth in last week
last_week_date = current_date - timedelta(days=7)
last_week_activity = activity_df[activity_df['date'] >= pd.to_datetime(last_week_date)]
last_week_growth = last_week_activity.groupby('username')['total'].sum().reset_index()
last_week_growth.columns = ['Username', 'Last Week Growth']
users_df = users_df.merge(last_week_growth, on='Username', how='left').fillna(0)

# Calculate inactive students (>7 days)
users_df['days_since_last_active'] = (current_date - pd.to_datetime(users_df['last_active'], errors='coerce')).dt.days
users_df['is_inactive'] = users_df['days_since_last_active'] > 7

# Calculate difficulty-wise averages
difficulty_avg = users_df[['Easy Solved', 'Medium Solved', 'Hard Solved']].mean().reset_index()
difficulty_avg.columns = ['Difficulty', 'Average Solved']

# Create Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server

# Define tabs
tabs = dbc.Tabs([
    dbc.Tab(label="Leaderboard", tab_id="leaderboard"),
    dbc.Tab(label="User Performance", tab_id="user-performance"),
    dbc.Tab(label="Difficulty Analysis", tab_id="difficulty-analysis"),
    dbc.Tab(label="Activity Trends", tab_id="activity-trends")
], id="tabs", active_tab="leaderboard")

# App layout
app.layout = dbc.Container([
    dbc.Row(dbc.Col(html.H1("LeetCode Dashboard", className="text-center my-4"))),
    dbc.Row(dbc.Col(tabs)),
    html.Div(id="tab-content")
], fluid=True)

# Leaderboard tab content
leaderboard_content = dbc.Container([
    dbc.Row([
        dbc.Col(html.H3("Top Performers", className="text-center mb-4"), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='top-3-chart'), width=12)
    ]),
    dbc.Row([
        dbc.Col(html.H4("Full Leaderboard", className="text-center mt-4"), width=12)
    ]),
    dbc.Row([
        dbc.Col(html.Div(id='full-leaderboard'), width=12)
    ])
])

# User performance tab content
user_performance_content = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H3("User Performance Analysis", className="text-center mb-4"),
            dcc.Dropdown(
                id='user-selector',
                options=[{'label': user, 'value': user} for user in users_df['Username']],
                value=users_df['Username'].iloc[0] if not users_df.empty else '',
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

# Difficulty analysis tab content
difficulty_content = dbc.Container([
    dbc.Row([
        dbc.Col(html.H3("Difficulty-wise Analysis", className="text-center mb-4"), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='difficulty-avg-chart'), width=6),
        dbc.Col(dcc.Graph(id='difficulty-distribution'), width=6)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='hard-solvers'), width=12)
    ])
])

# Activity trends tab content
activity_trends_content = dbc.Container([
    dbc.Row([
        dbc.Col(html.H3("Activity Trends", className="text-center mb-4"), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='daily-participation'), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='inactive-students-chart'), width=12)
    ])
])


# Callback to switch tabs
@app.callback(
    Output("tab-content", "children"),
    Input("tabs", "active_tab")
)
def render_tab_content(active_tab):
    if active_tab == "leaderboard":
        return leaderboard_content
    elif active_tab == "user-performance":
        return user_performance_content
    elif active_tab == "difficulty-analysis":
        return difficulty_content
    elif active_tab == "activity-trends":
        return activity_trends_content
    return "No tab selected"


# Leaderboard callbacks
@app.callback(
    Output('top-3-chart', 'figure'),
    Input('tabs', 'active_tab')
)
def update_top_3_chart(active_tab):
    if active_tab != "leaderboard" or users_df.empty:
        return go.Figure()

    top_3 = users_df.sort_values('Total', ascending=False).head(3)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[top_3.iloc[0]['Username']],
        y=[top_3.iloc[0]['Total']],
        name="1st Place",
        marker_color='gold',
        width=0.5
    ))
    fig.add_trace(go.Bar(
        x=[top_3.iloc[1]['Username']],
        y=[top_3.iloc[1]['Total']],
        name="2nd Place",
        marker_color='silver',
        width=0.5
    ))
    fig.add_trace(go.Bar(
        x=[top_3.iloc[2]['Username']],
        y=[top_3.iloc[2]['Total']],
        name="3rd Place",
        marker_color='#cd7f32',
        width=0.5
    ))

    fig.update_layout(
        title="Top 3 Performers",
        xaxis_title="Username",
        yaxis_title="Total Problems Solved",
        showlegend=False,
        xaxis={'categoryorder': 'array',
               'categoryarray': [top_3.iloc[1]['Username'], top_3.iloc[0]['Username'], top_3.iloc[2]['Username']]}
    )

    return fig


@app.callback(
    Output('full-leaderboard', 'children'),
    Input('tabs', 'active_tab')
)
def update_full_leaderboard(active_tab):
    if active_tab != "leaderboard" or users_df.empty:
        return "No data available"

    leaderboard_df = users_df.sort_values('Total', ascending=False)

    table = dbc.Table(
        [
            html.Thead(
                html.Tr([
                    html.Th("Rank"),
                    html.Th("Username"),
                    html.Th("Total"),
                    html.Th("Easy"),
                    html.Th("Medium"),
                    html.Th("Hard"),
                    html.Th("Streak")
                ])
            ),
            html.Tbody([
                html.Tr([
                    html.Td(i + 1),
                    html.Td(user['Username']),
                    html.Td(user['Total']),
                    html.Td(user['Easy Solved']),
                    html.Td(user['Medium Solved']),
                    html.Td(user['Hard Solved']),
                    html.Td(user['current_streak'])
                ]) for i, (_, user) in enumerate(leaderboard_df.iterrows())
            ])
        ],
        bordered=True,
        hover=True,
        responsive=True,
        striped=True,
    )

    return table


# User performance callbacks
@app.callback(
    Output('user-problems-chart', 'figure'),
    Input('user-selector', 'value')
)
def update_user_problems_chart(selected_user):
    if users_df.empty or selected_user not in users_df['Username'].values:
        return go.Figure()

    user_data = users_df[users_df['Username'] == selected_user].iloc[0]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=['Easy', 'Medium', 'Hard'],
        y=[user_data['Easy Solved'], user_data['Medium Solved'], user_data['Hard Solved']],
        marker_color=['#00B0A1', '#FFC154', '#FF6B6B'],
        text=[user_data['Easy Solved'], user_data['Medium Solved'], user_data['Hard Solved']],
        textposition='auto'
    ))

    fig.update_layout(
        title=f'Problems Solved by Difficulty',
        xaxis_title='Difficulty',
        yaxis_title='Count',
        showlegend=False
    )

    return fig


@app.callback(
    Output('user-activity-trend', 'figure'),
    Input('user-selector', 'value')
)
def update_user_activity_trend(selected_user):
    if activity_df.empty or selected_user not in activity_df['username'].values:
        return go.Figure()

    user_activity = activity_df[activity_df['username'] == selected_user].sort_values('date')

    if not user_activity.empty:
        user_activity['cumulative_total'] = user_activity['total'].cumsum()
    else:
        user_activity = pd.DataFrame({
            'date': [current_date - timedelta(days=1), current_date],
            'cumulative_total': [0, 0]
        })

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=user_activity['date'],
            y=user_activity['total'],
            name='Daily Problems Solved',
            marker_color='#4E79A7',
            opacity=0.7
        ),
        secondary_y=False
    )

    fig.add_trace(
        go.Scatter(
            x=user_activity['date'],
            y=user_activity['cumulative_total'],
            name='Cumulative Total',
            line=dict(color='#F28E2B', width=2)
        ),
        secondary_y=True
    )

    fig.update_layout(
        title=f'Activity Trend',
        xaxis_title='Date',
        hovermode='x unified'
    )

    fig.update_yaxes(title_text='Daily Problems Solved', secondary_y=False)
    fig.update_yaxes(title_text='Cumulative Problems Solved', secondary_y=True)

    return fig


@app.callback(
    Output('user-details-card', 'children'),
    Input('user-selector', 'value')
)
def update_user_details_card(selected_user):
    if users_df.empty or selected_user not in users_df['Username'].values:
        return "No data available for this user"

    user_data = users_df[users_df['Username'] == selected_user].iloc[0]

    card = dbc.Card([
        dbc.CardBody([
            html.H4(selected_user, className="card-title"),
            dbc.Row([
                dbc.Col([
                    html.P("Total Problems Solved", className="card-text"),
                    html.H4(f"{user_data['Total']}", className="card-text text-primary")
                ], width=3),
                dbc.Col([
                    html.P("Current Streak", className="card-text"),
                    html.H4(f"{user_data['current_streak']} days", className="card-text text-success")
                ], width=3),
                dbc.Col([
                    html.P("Longest Streak", className="card-text"),
                    html.H4(f"{user_data['longest_streak']} days", className="card-text text-info")
                ], width=3),
                dbc.Col([
                    html.P("Last Active", className="card-text"),
                    html.H4(f"{user_data['last_active']}", className="card-text text-warning")
                ], width=3),
            ]),
        ])
    ])

    return card


# Difficulty analysis callbacks
@app.callback(
    Output('difficulty-avg-chart', 'figure'),
    Input('tabs', 'active_tab')
)
def update_difficulty_avg_chart(active_tab):
    if active_tab != "difficulty-analysis" or difficulty_avg.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=difficulty_avg['Difficulty'],
        y=difficulty_avg['Average Solved'],
        marker_color=['#00B0A1', '#FFC154', '#FF6B6B'],
        text=difficulty_avg['Average Solved'],
        textposition='auto'
    ))

    fig.update_layout(
        title='Average Problems Solved by Difficulty',
        xaxis_title='Difficulty',
        yaxis_title='Average Solved',
        showlegend=False
    )

    return fig


@app.callback(
    Output('difficulty-distribution', 'figure'),
    Input('tabs', 'active_tab')
)
def update_difficulty_distribution(active_tab):
    if active_tab != "difficulty-analysis" or users_df.empty:
        return go.Figure()

    fig = go.Figure()

    fig.add_trace(go.Box(
        y=users_df['Easy Solved'],
        name='Easy',
        marker_color='#00B0A1'
    ))

    fig.add_trace(go.Box(
        y=users_df['Medium Solved'],
        name='Medium',
        marker_color='#FFC154'
    ))

    fig.add_trace(go.Box(
        y=users_df['Hard Solved'],
        name='Hard',
        marker_color='#FF6B6B'
    ))

    fig.update_layout(
        title='Distribution of Problems Solved by Difficulty',
        yaxis_title='Problems Solved',
        boxmode='group'
    )

    return fig


@app.callback(
    Output('hard-solvers', 'figure'),
    Input('tabs', 'active_tab')
)
def update_hard_solvers(active_tab):
    if active_tab != "difficulty-analysis" or users_df.empty:
        return go.Figure()

    top_hard_solvers = users_df.sort_values('Hard Solved', ascending=False).head(10)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=top_hard_solvers['Username'],
        y=top_hard_solvers['Hard Solved'],
        marker_color='#FF6B6B',
        text=top_hard_solvers['Hard Solved'],
        textposition='auto'
    ))

    fig.update_layout(
        title='Top 10 Hard Problem Solvers',
        xaxis_title='Username',
        yaxis_title='Hard Problems Solved'
    )

    return fig


# Activity trends callbacks
@app.callback(
    Output('daily-participation', 'figure'),
    Input('tabs', 'active_tab')
)
def update_daily_participation(active_tab):
    if active_tab != "activity-trends" or activity_df.empty:
        return go.Figure()

    daily_participation = activity_df.groupby('date')['username'].nunique().reset_index()
    daily_participation.columns = ['date', 'active_users']
    total_users = len(users_df)
    daily_participation['pct_active'] = (daily_participation['active_users'] / total_users) * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_participation['date'],
        y=daily_participation['pct_active'],
        name='% Active',
        line=dict(color='#4E79A7')
    ))

    fig.update_layout(
        title='Daily Participation Rate',
        xaxis_title='Date',
        yaxis_title='Percentage of Students Active',
        yaxis=dict(ticksuffix='%')
    )

    return fig


@app.callback(
    Output('inactive-students-chart', 'figure'),
    Input('tabs', 'active_tab')
)
def update_inactive_students_chart(active_tab):
    if active_tab != "activity-trends" or users_df.empty:
        return go.Figure()

    inactive_users = users_df[users_df['is_inactive']].sort_values('days_since_last_active', ascending=False)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=inactive_users['Username'],
        y=inactive_users['days_since_last_active'],
        marker_color='#FF6B6B',
        text=inactive_users['days_since_last_active'],
        textposition='auto'
    ))

    fig.update_layout(
        title='Inactive Students (>7 days)',
        xaxis_title='Username',
        yaxis_title='Days Inactive'
    )

    return fig


if __name__ == '__main__':
    app.run(debug=True)