import csv
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# LeetCode GraphQL endpoint (no CSRF token needed for this query)
headers = {
    'authority': 'leetcode.com',
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'referer': 'https://leetcode.com/',
}

def load_usernames(filename="usernames.txt"):
    with open(filename, 'r') as file:
        return [line.strip() for line in file if line.strip()]

usernames = load_usernames()

def fetch_leetcode_data(username):
    """
    Fetches user data using LeetCode's GraphQL endpoint and returns a tuple:
    (username, total_solved, easy_solved, medium_solved, hard_solved)
    """
    url = 'https://leetcode.com/graphql'
    json_data = {
        'query': '''
        query getUserProfile($username: String!) {
            matchedUser(username: $username) {
                submitStats: submitStatsGlobal {
                    acSubmissionNum {
                        difficulty
                        count
                    }
                }
            }
        }
        ''',
        'variables': {'username': username},
    }

    try:
        response = requests.post(url, headers=headers, json=json_data, timeout=5)
        response.raise_for_status()
        data = response.json()
        # Validate that we got data for the user
        if not data.get("data") or not data["data"].get("matchedUser"):
            # No data found for the user; return zeros
            return (username, 0, 0, 0, 0)

        ac_stats = data["data"]["matchedUser"]["submitStats"]["acSubmissionNum"]
        solved_counts = {item["difficulty"]: item["count"] for item in ac_stats}
        total = solved_counts.get("All", 0)
        easy = solved_counts.get("Easy", 0)
        medium = solved_counts.get("Medium", 0)
        hard = solved_counts.get("Hard", 0)
        return (username, total, easy, medium, hard)

    except Exception as e:
        # In case of any error, log error counts as 0 (or you could mark them differently)
        return (username, 0, 0, 0, 0)


def save_to_csv(user_data, filename="./output/leetcode_all_users.csv"):
    # If the file exists, delete it first.
    if os.path.exists(filename):
        os.remove(filename)

    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        # Write header row
        writer.writerow(['Username', 'Total', 'EasySolved', 'MediumSolved', 'HardSolved'])
        # Write one row per user
        for row in user_data:
            writer.writerow(row)


def main(usernames):
    user_data = []
    print("Fetching data in parallel...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_leetcode_data, user): user for user in usernames}
        for future in as_completed(futures):
            user_data.append(future.result())

    save_to_csv(user_data)
    print("✅ CSV saved as leetcode_all_users.csv")




if __name__ == "__main__":
    # For standalone execution, still load from file
    def load_usernames(filename="usernames.txt"):
        with open(filename, 'r') as file:
            return [line.strip() for line in file if line.strip()]

    usernames = load_usernames()
    main(usernames)
