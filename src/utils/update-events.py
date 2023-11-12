import os
import requests
import re
from datetime import datetime, timezone
from github import Github

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
PAT = os.getenv("GH_PAT")  # Personal Access Token for GitHub
REPO = os.getenv("REPO_NAME")
FILE_PATH = "src/content/post/events.md"


# Function to authenticate with GitHub
def authenticate_with_github(GH_PAT):
    return Github(GH_PAT)


# Function to get file from GitHub
def get_github_file(repo_name, file_path, GH_PAT):
    g = authenticate_with_github(GH_PAT)
    repo = g.get_repo(repo_name)
    contents = repo.get_contents(file_path, ref="main")
    return contents.decoded_content.decode("utf-8"), contents.sha


# Function to update file on GitHub
def update_github_file(
    repo_name, file_path, content, sha, GH_PAT, commit_message="Update events"
):
    g = authenticate_with_github(GH_PAT)
    repo = g.get_repo(repo_name)
    repo.update_file(file_path, commit_message, content, sha, branch="main")


# Function to fetch channel name for events from Discord
def fetch_discord_channel_name(channel_id, bot_token):
    try:
        url = f"https://discord.com/api/v9/channels/{channel_id}"
        headers = {"Authorization": f"Bot {bot_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        channel = response.json()
        return channel.get("name", "Unknown Channel")
    except Exception as e:
        print(f"Error fetching channel name: {e}")
        return "Unknown Channel"


# Function to fetch events from Discord
def fetch_discord_events(guild_id, bot_token):
    url = f"https://discord.com/api/v9/guilds/{guild_id}/scheduled-events"
    headers = {"Authorization": f"Bot {bot_token}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        events = response.json()
        return process_discord_events(events, bot_token)
    except requests.RequestException as e:
        print(f"Error fetching events: {e}")
        return []


# Process and return events in a structured format
def process_discord_events(events, bot_token):
    structured_events = []
    for event in events:
        if event["status"] == 1:  # 1 is for SCHEDULED events
            start_time = datetime.fromisoformat(event["scheduled_start_time"])
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            channel_id = event.get("channel_id")
            channel_name = (
                fetch_discord_channel_name(channel_id, bot_token)
                if channel_id
                else "No location"
            )
            event_name = event["name"].strip()
            structured_events.append(
                {
                    "id": event["id"],  # Include the event ID
                    "name": event_name,
                    "date": start_time.date(),
                    "description": event["description"].strip(),
                    "location": channel_name,
                    "section": "upcoming"
                    if start_time.date() >= datetime.now().date()
                    else "past",
                }
            )
    return structured_events


# Function to parse markdown content and extract events
def parse_markdown(content):
    frontmatter, events_content = content.split("---\n", 2)[1:3]
    current_datetime = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    frontmatter = re.sub(
        r"publishDate:.*", f"publishDate: {current_datetime}", frontmatter
    )

    upcoming_pattern = r"# Upcoming Events\n\n(.*?)(\n\n#|$)"
    past_pattern = r"# Past Events\n\n(.*?)(\n\n#|$)"

    upcoming_content = re.search(upcoming_pattern, events_content, re.DOTALL).group(1)
    past_content = re.search(past_pattern, events_content, re.DOTALL).group(1)

    event_pattern = r"(## [^\n]+)\nID: ([^\n]+)\nDate: ([^\n]+)\nDescription:\n([^\n]+(?:\n\n[^\n]+)*)\nLocation: ([^\n]+)"
    upcoming_events = re.findall(event_pattern, upcoming_content, re.DOTALL)
    past_events = re.findall(event_pattern, past_content, re.DOTALL)

    def process_events(matches, section):
        events = []
        for match in matches:
            name, event_id, date_str, description, location = match
            date = datetime.strptime(date_str, "%b %d, %Y").date()
            events.append(
                {
                    "name": name.strip(),
                    "id": event_id,
                    "date": date,
                    "description": description.strip(),
                    "location": location,
                    "section": section,
                }
            )
        return events

    upcoming_events = process_events(upcoming_events, "upcoming")
    past_events = process_events(past_events, "past")
    return frontmatter, upcoming_events, past_events


# Function to merge and generate markdown
def merge_and_generate_markdown(
    frontmatter, new_events, existing_upcoming_events, existing_past_events
):
    today = datetime.now().date()
    all_events = {}

    # Categorize and add existing events
    for event in existing_upcoming_events + existing_past_events:
        event["section"] = "upcoming" if event["date"] >= today else "past"
        all_events[event["id"]] = event

    # Merge new events
    for event in new_events:
        all_events[event["id"]] = event

    # Categorize new events correctly
    for event_id, event in all_events.items():
        all_events[event_id]["section"] = (
            "upcoming" if event["date"] >= today else "past"
        )

    # Generate Markdown content for upcoming and past events
    upcoming_events_md = "\n\n".join(
        f"{event['name']}\nID: {event['id']}\nDate: {event['date'].strftime('%b %d, %Y')}\nDescription:\n{event['description']}\nLocation: {event['location']}"
        for event in all_events.values()
        if event["section"] == "upcoming"
    )
    past_events_md = "\n\n".join(
        f"{event['name']}\nID: {event['id']}\nDate: {event['date'].strftime('%b %d, %Y')}\nDescription:\n{event['description']}\nLocation: {event['location']}"
        for event in all_events.values()
        if event["section"] == "past"
    )

    updated_content = f"---\n{frontmatter}---\n\n# Upcoming Events\n\n{upcoming_events_md}\n\n# Past Events\n\n{past_events_md}\n"
    return updated_content


def main():
    new_events = fetch_discord_events(GUILD_ID, BOT_TOKEN)
    try:
        content, sha = get_github_file(REPO, FILE_PATH, PAT)
        frontmatter, existing_upcoming_events, existing_past_events = parse_markdown(
            content
        )
        updated_content = merge_and_generate_markdown(
            frontmatter, new_events, existing_upcoming_events, existing_past_events
        )
        update_github_file(REPO, FILE_PATH, updated_content, sha, PAT)
        print("The events.md file has been updated successfully on GitHub.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
