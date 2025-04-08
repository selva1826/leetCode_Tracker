import requests
import json
import csv
import time
import datetime
import asyncio
import aiohttp
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta


class LeetCodeScraper:
    def __init__(self, max_workers=5, rate_limit=15):
        """
        Initialize the LeetCode scraper with concurrency settings

        Args:
            max_workers (int): Maximum number of concurrent workers
            rate_limit (int): Maximum requests per second
        """
        self.max_workers = max_workers
        self.rate_limit = rate_limit
        self.session = None
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://leetcode.com/",
            "Origin": "https://leetcode.com"
        }

    async def _init_session(self):
        """Initialize aiohttp session"""
        if self.session is None:
            self.session = aiohttp.ClientSession(headers=self.headers)

    async def close_session(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def get_user_profile(self, username):
        """Get basic user profile data"""
        await self._init_session()

        query = """
        query getUserProfile($username: String!) {
            matchedUser(username: $username) {
                username
                submitStats {
                    acSubmissionNum {
                        difficulty
                        count
                    }
                }
            }
        }
        """

        variables = {"username": username}
        payload = {"query": query, "variables": variables}

        url = "https://leetcode.com/graphql"

        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                print(f"Error fetching profile for {username}: HTTP {response.status}")
                return None

            data = await response.json()

            # Check if user exists and has data
            if data.get("data") is None or data["data"].get("matchedUser") is None:
                print(f"User '{username}' not found")
                return None

            return data["data"]

    async def get_recent_submissions(self, username):
        """Get submission history for the past 7 days"""
        await self._init_session()

        query = """
        query recentSubmissions($username: String!) {
            recentSubmissionList(username: $username, limit: 100) {
                title
                timestamp
                statusDisplay
                lang
                id
                titleSlug
            }
        }
        """

        variables = {"username": username}
        payload = {"query": query, "variables": variables}

        url = "https://leetcode.com/graphql"

        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                print(f"Error fetching submissions for {username}: HTTP {response.status}")
                return None

            data = await response.json()

            if data.get("data") is None or data["data"].get("recentSubmissionList") is None:
                print(f"No submission data for '{username}'")
                return []

            return data["data"]["recentSubmissionList"]

    async def get_problem_difficulty(self, title_slug):
        """Get problem difficulty level"""
        await self._init_session()

        query = """
        query problemData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                difficulty
            }
        }
        """

        variables = {"titleSlug": title_slug}
        payload = {"query": query, "variables": variables}

        url = "https://leetcode.com/graphql"

        try:
            async with self.session.post(url, json=payload) as response:
                if response.status != 200:
                    return "Unknown"

                data = await response.json()

                if data.get("data") is None or data["data"].get("question") is None:
                    return "Unknown"

                return data["data"]["question"]["difficulty"]
        except Exception as e:
            print(f"Error fetching difficulty for {title_slug}: {e}")
            return "Unknown"

    def parse_timestamp(self, timestamp_value):
        """
        Parse timestamp that could be in different formats
        """
        if isinstance(timestamp_value, int):  # Unix timestamp as integer
            return datetime.fromtimestamp(timestamp_value)
        elif isinstance(timestamp_value, str):
            try:
                # Try parsing as int first (string representation of unix timestamp)
                return datetime.fromtimestamp(int(timestamp_value))
            except ValueError:
                # Try different date formats
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(timestamp_value, fmt)
                    except ValueError:
                        continue

                # If all formats failed, use current date
                print(f"Warning: Could not parse timestamp '{timestamp_value}', using current date")
                return datetime.now()
        else:
            # Default to current date if timestamp is not recognized
            print(f"Warning: Unrecognized timestamp format: {type(timestamp_value)}, using current date")
            return datetime.now()

    async def process_user(self, username):
        """Process a single user's data"""
        # Get basic profile stats
        profile_data = await self.get_user_profile(username)
        if not profile_data:
            return {
                "username": username,
                "error": "Failed to fetch data",
                "problems_solved": {"easy": 0, "medium": 0, "hard": 0},
                "total_solved": 0,
                "daily_activity": []
            }

        # Process submission stats
        stats = {"username": username, "problems_solved": {}}

        try:
            submission_stats = profile_data["matchedUser"]["submitStats"]["acSubmissionNum"]
            for item in submission_stats:
                difficulty = item["difficulty"]
                count = item["count"]

                if difficulty == "All":
                    stats["total_solved"] = count
                else:
                    stats["problems_solved"][difficulty.lower()] = count
        except (KeyError, TypeError) as e:
            print(f"Error processing stats for {username}: {e}")
            stats["problems_solved"] = {"easy": 0, "medium": 0, "hard": 0}
            stats["total_solved"] = 0

        # Get recent submissions for 7-day activity
        submissions = await self.get_recent_submissions(username)

        # Get current date and date 7 days ago
        today = datetime.now()
        week_ago = today - timedelta(days=7)

        # Process submissions into daily activity
        daily_activity = {}

        # Initialize dictionary with last 7 days
        for i in range(7):
            day = today - timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            daily_activity[date_str] = {
                "date": date_str,
                "easy": 0,
                "medium": 0,
                "hard": 0,
                "total": 0,
                "problems": []
            }

        # Add real submission data
        if submissions:
            # Create a cache for problem difficulties to avoid repeated API calls
            difficulty_cache = {}

            # Dictionary to track unique problems solved per day
            unique_problems_per_day = {}

            for submission in submissions:
                # Print raw timestamp data for debugging
                print(f"Debug - Raw timestamp for {username}: {submission.get('timestamp', 'No timestamp')}")

                try:
                    # Handle different timestamp formats
                    timestamp = self.parse_timestamp(submission.get("timestamp", ""))
                    date_str = timestamp.strftime("%Y-%m-%d")

                    # Skip if older than 7 days
                    if timestamp < week_ago:
                        continue

                    # Skip if not a successful submission
                    if submission.get("statusDisplay") != "Accepted":
                        continue

                    # Initialize dict for this day if not exists
                    if date_str not in unique_problems_per_day:
                        unique_problems_per_day[date_str] = set()

                    # Skip if this problem already counted for this day
                    if submission["titleSlug"] in unique_problems_per_day[date_str]:
                        continue

                    # Mark this problem as counted for this day
                    unique_problems_per_day[date_str].add(submission["titleSlug"])

                    # Get problem difficulty
                    title_slug = submission["titleSlug"]
                    if title_slug in difficulty_cache:
                        difficulty = difficulty_cache[title_slug]
                    else:
                        difficulty = await self.get_problem_difficulty(title_slug)
                        difficulty_cache[title_slug] = difficulty

                    difficulty = difficulty.lower()

                    # Skip if day is not in our 7-day window
                    if date_str not in daily_activity:
                        continue

                    # Increment counters
                    if difficulty in ["easy", "medium", "hard"]:
                        daily_activity[date_str][difficulty] += 1
                    daily_activity[date_str]["total"] += 1
                    daily_activity[date_str]["problems"].append({
                        "title": submission["title"],
                        "difficulty": difficulty
                    })
                except Exception as e:
                    print(f"Error processing submission for {username}: {e}")
                    continue

        # Convert dict to list sorted by date
        stats["daily_activity"] = sorted(
            daily_activity.values(),
            key=lambda x: x["date"],
            reverse=True
        )

        return stats

    async def process_multiple_users(self, usernames):
        """Process multiple users concurrently"""
        await self._init_session()

        tasks = []
        for username in usernames:
            # Add small delay between task creations to avoid overwhelming the server
            await asyncio.sleep(1.0 / self.rate_limit)
            tasks.append(self.process_user(username))

        results = await asyncio.gather(*tasks)

        # Convert list of results to dictionary keyed by username
        return {result["username"]: result for result in results}



def save_daily_activity_to_csv(results, filename="./output/leetcode_daily_activity.csv"):
    """Save daily activity to CSV file"""
    rows = []

    for username, data in results.items():
        # Skip users with errors
        if "error" in data:
            continue

        for day in data["daily_activity"]:
            rows.append({
                "username": username,
                "date": day["date"],
                "easy": day["easy"],
                "medium": day["medium"],
                "hard": day["hard"],
                "total": day["total"]
            })

    # If no rows, create empty file with headers
    if not rows:
        rows = [{"username": "", "date": "", "easy": 0, "medium": 0, "hard": 0, "total": 0}]

    # Write to CSV
    keys = rows[0].keys()
    with open(filename, 'w', newline='') as f:
        dict_writer = csv.DictWriter(f, keys)
        dict_writer.writeheader()
        dict_writer.writerows(rows)

    print(f"Daily activity saved to {filename}")


async def main(usernames):
    """Main function to handle async execution"""
    scraper = LeetCodeScraper(max_workers=5, rate_limit=10)

    try:
        # Process all users
        results = await scraper.process_multiple_users(usernames)

        # Save daily activity to CSV
        save_daily_activity_to_csv(results)

        # Print summary
        print("\n--- Summary ---")
        for username, stats in results.items():
            print(f"\n{username} Statistics:")
            if "error" in stats:
                print(f"Error: {stats['error']}")
                continue

            print(f"Total Problems Solved: {stats.get('total_solved', 'N/A')}")
            problems = stats.get('problems_solved', {})
            print(f"Easy: {problems.get('easy', 'N/A')}")
            print(f"Medium: {problems.get('medium', 'N/A')}")
            print(f"Hard: {problems.get('hard', 'N/A')}")

            print("\nRecent Activity:")
            for i, day in enumerate(stats["daily_activity"][:5]):  # Show only last 5 days
                print(f"  {day['date']}: {day['total']} problems (E:{day['easy']} M:{day['medium']} H:{day['hard']})")

    finally:
        # Close session
        await scraper.close_session()


# Modified function for non-async debugging
def debug_leetcode_api(username):
    """
    Debug function to directly check the recent submissions format
    """
    url = "https://leetcode.com/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    query = """
    query recentSubmissions($username: String!) {
        recentSubmissionList(username: $username, limit: 5) {
            title
            timestamp
            statusDisplay
            lang
        }
    }
    """

    variables = {"username": username}
    payload = {"query": query, "variables": variables}

    response = requests.post(url, headers=headers, json=payload)
    print(f"Status code: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        if "data" in data and "recentSubmissionList" in data["data"]:
            submissions = data["data"]["recentSubmissionList"]
            if submissions:
                print(f"Sample submission timestamp: {submissions[0].get('timestamp')}")
                print(f"Sample timestamp type: {type(submissions[0].get('timestamp'))}")
                print(f"First few submissions: {submissions[:2]}")
            else:
                print("No submissions found")
        else:
            print("Unexpected response format")
            print(f"Response: {data}")
    else:
        print(f"Error response: {response.text}")

    return response.json() if response.status_code == 200 else None


# Run the program
if __name__ == "__main__":
    #For standalone execution, still load from file
    def load_usernames(filename="usernames.txt"):
        with open(filename, 'r') as file:
            return [line.strip() for line in file if line.strip()]

    usernames = load_usernames()
    asyncio.run(main(usernames))
