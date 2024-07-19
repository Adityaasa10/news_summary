"""
import re
import feedparser
from bs4 import BeautifulSoup
from dateutil.parser import parse
import cohere
from cohere.error import *
import requests
import sqlite3
import article_parser
from datetime import datetime
from flask import Flask, render_template, request, redirect
import sqlite3
import markdown2
from dotenv import load_dotenv
import os
import time

# Loading dotenv file
load_dotenv() 

    # Read the .opml file which is the standard format for files containing RSS Links.
from bs4 import BeautifulSoup

def read_opml_file():
    with open("news-links.opml", "r", encoding='utf-8') as opml_file:
        soup = BeautifulSoup(opml_file.read(), "lxml-xml")
        feed_urls = [outline.get("xmlUrl") for outline in soup.find_all("outline") if outline.get("xmlUrl")]
    return feed_urls

def ai_summarizer(news_info):
    # Get Your own key from Cohere Website 
    cohere_api_key = os.getenv("API-KEY")
    co = cohere.Client(cohere_api_key)

    # Number of times to Retry when there is an error
    max_attempts = 7

    # Requesting AI to summarize the Information and defining the maximun amount of tokens to be recieved.
    for attempt in range(1, max_attempts + 1):
        try:
            summary = co.summarize(text=news_info,
                                   model="summarize-xlarge",
                                   length="long",
                                   format="bullets",
                                   temperature=0.9)

            return summary.summary
        except CohereAPIError as api_error:
            print(f"Error: {api_error.message}")
            if attempt < max_attempts:
                print(f"Retrying attempt {attempt + 1}...")
                time.sleep(1)  # Adding a small delay before retrying
            else:
                print(f"Maximum retry attempts reached. Unable to summarize.")
                break

def sqlite_data(post):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS rss_feed
                    (date TEXT, title TEXT, full_content TEXT, summarized_content TEXT, link TEXT, author TEXT)''')

    # Check if a record with the same title and link already exists in the database.
    cursor.execute("SELECT * FROM rss_feed WHERE title = ? AND link = ?",
                   (post['title'], post['link']))
    existing_record = cursor.fetchone()

    if existing_record:
        print("Duplicate data. Not saved.")
    else:
        # If there is no existing record then save it to the file.
        cursor.execute("INSERT INTO rss_feed VALUES (?, ?, ?, ?, ?, ?)",
                       (post['published'], post['title'], post['full_content'], post['summarized_content'], post['link'], post['author']))
        conn.commit()
        print("Data Saved Succesfully.")
        print("------------------------------------------------------------")

    conn.close()

def sort_data_by_date(data_list):
    sorted_data = sorted(data_list, key=lambda x: x['date'], reverse=True)
    return sorted_data

    # Clean the data removing whitespaces and all the blank lines. 
def remove_blank_lines(_full_content):
    return re.sub(r'^\s*\n', '', _full_content, flags=re.MULTILINE)

def article_info(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    }

    try:
        # Requestion information from website by providing url and headers using requests.
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        html = response.text
        # Sending the given html to the article_parser to extract only useful information and convert it into markdown format. 
        title, content = article_parser.parse(url=url, html=html, output='markdown', timeout=5)
        return content
    
    # Handle all the errors while visiting the website.
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the article: {e}")
        # Return nothing.
        return ""

def parse_rss_feed(url):
    print("Trying to fetch rss feeds.")
    feed = feedparser.parse(url)
    posts = []

    for post in feed.entries:
        post_url = post.link
        print(post_url)

        # Check if the post already exists in the database by title and link
        existing_post = check_existing_post(post.title, post_url)

        if existing_post:
            print("Post already exists. Skipping.")
            print("------------------------------------------------------------")
            posts.append(existing_post)

        else:
            # Saving the information recieved from article_parse in full_content
            full_content = article_info(post_url)
            full_content = remove_blank_lines(full_content)
            # Sending that Informaton to AI model to summarize and save to summarized_content
            summarized_content = ai_summarizer(full_content)
            if 'published' in post:
                published_date = parse(post.published)
            else:
                # Handle the case where 'published' date is missing
                published_date = None
            
            if 'author' in post:
                author = post.author
            else:
                # Handle the case where author information is missing
                author = "Not mentioned" 

            # Structure the data in dictionary format.
            post_data = {
                'title': post.title,
                'author': author,
                'published': published_date,
                'link': post_url,
                'full_content': full_content,
                'summarized_content': summarized_content

            }

            posts.append(post_data)
            sqlite_data(post_data)

    return posts

def check_existing_post(title, link):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS rss_feed
                    (date TEXT, title TEXT, full_content TEXT, summarized_content TEXT, link TEXT, author TEXT)''')
    cursor.execute("SELECT * FROM rss_feed WHERE title = ? AND link = ?", (title, link))
    existing_record = cursor.fetchone()
    
    conn.close()
    
    if existing_record:
        return {
            'title': existing_record[1],
            'author': existing_record[5],
            'published': existing_record[0],
            'link': existing_record[4],
            'full_content': existing_record[2]
        }
    else:
        return None

app = Flask(__name__)

# Function to fetch data from the database for web.
def get_data(sort_order):
    data_list = []
    sorted_data_by_date = []  

    try:
        conn = sqlite3.connect('summarizer-data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rss_feed')
        data = cursor.fetchall()

        for row in data:
            full_content = markdown2.markdown(row[2], extras=["markdown-urls"])
            summarized_content = markdown2.markdown(row[3] if row[3] is not None else "", extras=["markdown-urls"])
            date_time = datetime.fromisoformat(row[0])
            date_iso = date_time.isoformat()

            data_dict = {
                'date': date_iso,
                'title': row[1],
                'full_content': full_content,
                'summarized_content': summarized_content,
                'link': row[4],
                'author': row[5]
            }

            data_list.append(data_dict)

        if sort_order == 'desc':
            sorted_data_by_date = sorted(data_list, key=lambda x: x['date'], reverse=True)
        else:  # sort_order == 'asc':
            sorted_data_by_date = sorted(data_list, key=lambda x: x['date'], reverse=False)

        conn.close()
    except sqlite3.OperationalError as e:
        print("Database file not found. Running without it.")

    return sorted_data_by_date

def format_datetime(dateTimeString):
    date = datetime.fromisoformat(dateTimeString)  # Parse the ISO 8601 date string
    formatted_date = date.strftime("%A, %B %d, %Y %I:%M %p")
    return formatted_date

# This sunction run when the code is executed and creates a html website at local Host.
@app.route('/', methods=['GET', 'POST'])
def index():
    sort_order = 'desc'
    if request.method == 'POST':
        sort_order = request.form.get('sortorder')
    data = get_data(sort_order)
    
    return render_template('index.html', data=data, formatDateTime=format_datetime)

# When summarized button is clicked then this function starts.
@app.route('/summarize', methods=['GET'])
def main():
    urls = read_opml_file()
    for url in urls:
        print("Processing URL:", url)
        parse_rss_feed(url)

    return redirect("/") 
    
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
"""
"""
import re
import feedparser
from bs4 import BeautifulSoup
from dateutil.parser import parse
import requests
import sqlite3
import article_parser
from datetime import datetime
from flask import Flask, render_template, request, redirect
import markdown2
from dotenv import load_dotenv
import os
import time
import google.generativeai as genai

# Loading dotenv file
load_dotenv()

# Configure the Gemini API
genai.configure(api_key="AIzaSyBMiFo-OCnXTj7QYKN8HojbjtsaIRXMxb8")


def read_opml_file():
    with open("news-links.opml", "r", encoding='utf-8') as opml_file:
        soup = BeautifulSoup(opml_file.read(), "lxml-xml")
        feed_urls = [outline.get("xmlUrl") for outline in soup.find_all("outline") if outline.get("xmlUrl")]
    return feed_urls


def ai_summarizer(news_info):
    max_attempts = 7
    model = genai.GenerativeModel('gemini-pro')

    for attempt in range(1, max_attempts + 1):
        try:
            prompt = (
                "You are a person working at a news agency or newspaper printing press, "
                "your task is to summarize the given news articles in at most 100 words and give it in form of bullet points:\n\n"
                f"{news_info}"
            )
            response = model.generate_content(prompt)
            print(response)
            return response.text
        except Exception as e:
            print(f"Error: {str(e)}")
            if attempt < max_attempts:
                print(f"Retrying attempt {attempt + 1}...")
                time.sleep(1)
            else:
                print(f"Maximum retry attempts reached. Unable to summarize.")
                break


def sqlite_data(post):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS rss_feed
                    (date TEXT, title TEXT, full_content TEXT, summarized_content TEXT, link TEXT, author TEXT)''')

    cursor.execute("SELECT * FROM rss_feed WHERE title = ? AND link = ?",
                   (post['title'], post['link']))
    existing_record = cursor.fetchone()

    if existing_record:
        print("Duplicate data. Not saved.")
    else:
        cursor.execute("INSERT INTO rss_feed VALUES (?, ?, ?, ?, ?, ?)",
                       (
                       post['published'], post['title'], post['full_content'], post['summarized_content'], post['link'],
                       post['author']))
        conn.commit()
        print("Data Saved Successfully.")
        print("------------------------------------------------------------")

    conn.close()


def sort_data_by_date(data_list):
    sorted_data = sorted(data_list, key=lambda x: x['date'], reverse=True)
    return sorted_data


def remove_blank_lines(_full_content):
    return re.sub(r'^\s*\n', '', _full_content, flags=re.MULTILINE)


def article_info(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        html = response.text
        title, content = article_parser.parse(url=url, html=html, output='markdown', timeout=5)
        return content

    except requests.exceptions.RequestException as e:
        print(f"Error fetching the article: {e}")
        return ""


def parse_rss_feed(url):
    print("Trying to fetch rss feeds.")
    feed = feedparser.parse(url)
    posts = []

    for post in feed.entries:
        post_url = post.link
        print(post_url)

        existing_post = check_existing_post(post.title, post_url)

        if existing_post:
            print("Post already exists. Skipping.")
            print("------------------------------------------------------------")
            posts.append(existing_post)

        else:
            full_content = article_info(post_url)
            full_content = remove_blank_lines(full_content)
            summarized_content = ai_summarizer(full_content)
            if 'published' in post:
                published_date = parse(post.published)
            else:
                published_date = None

            if 'author' in post:
                author = post.author
            else:
                author = "Not mentioned"

            post_data = {
                'title': post.title,
                'author': author,
                'published': published_date,
                'link': post_url,
                'full_content': full_content,
                'summarized_content': summarized_content
            }

            posts.append(post_data)
            sqlite_data(post_data)

    return posts


def check_existing_post(title, link):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS rss_feed
                    (date TEXT, title TEXT, full_content TEXT, summarized_content TEXT, link TEXT, author TEXT)''')
    cursor.execute("SELECT * FROM rss_feed WHERE title = ? AND link = ?", (title, link))
    existing_record = cursor.fetchone()

    conn.close()

    if existing_record:
        return {
            'title': existing_record[1],
            'author': existing_record[5],
            'published': existing_record[0],
            'link': existing_record[4],
            'full_content': existing_record[2]
        }
    else:
        return None


app = Flask(__name__)


def get_data(sort_order):
    data_list = []
    sorted_data_by_date = []

    try:
        conn = sqlite3.connect('summarizer-data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rss_feed')
        data = cursor.fetchall()

        for row in data:
            full_content = markdown2.markdown(row[2], extras=["markdown-urls"])
            summarized_content = markdown2.markdown(row[3] if row[3] is not None else "", extras=["markdown-urls"])
            date_time = datetime.fromisoformat(row[0])
            date_iso = date_time.isoformat()

            data_dict = {
                'date': date_iso,
                'title': row[1],
                'full_content': full_content,
                'summarized_content': summarized_content,
                'link': row[4],
                'author': row[5]
            }

            data_list.append(data_dict)

        if sort_order == 'desc':
            sorted_data_by_date = sorted(data_list, key=lambda x: x['date'], reverse=True)
        else:
            sorted_data_by_date = sorted(data_list, key=lambda x: x['date'], reverse=False)

        conn.close()
    except sqlite3.OperationalError as e:
        print("Database file not found. Running without it.")

    return sorted_data_by_date


def format_datetime(dateTimeString):
    date = datetime.fromisoformat(dateTimeString)
    formatted_date = date.strftime("%A, %B %d, %Y %I:%M %p")
    return formatted_date


@app.route('/', methods=['GET', 'POST'])
def index():
    sort_order = 'desc'
    if request.method == 'POST':
        sort_order = request.form.get('sortorder')
    data = get_data(sort_order)

    return render_template('index.html', data=data, formatDateTime=format_datetime)


@app.route('/summarize', methods=['GET'])
def main():
    urls = read_opml_file()
    for url in urls:
        print("Processing URL:", url)
        parse_rss_feed(url)

    return redirect("/")


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
    """
import re
import feedparser
from bs4 import BeautifulSoup
from dateutil.parser import parse
import requests
import sqlite3
import article_parser
from datetime import datetime
from flask import Flask, render_template, request, redirect
import markdown2
from dotenv import load_dotenv
import os
import time
import google.generativeai as genai

# Loading dotenv file
load_dotenv()

# Configure the Gemini API
genai.configure(api_key="AIzaSyBMiFo-OCnXTj7QYKN8HojbjtsaIRXMxb8")


def categorize_article(title, content):
    max_attempts = 3
    model = genai.GenerativeModel('gemini-pro')

    for attempt in range(1, max_attempts + 1):
        try:
            prompt = (
                "Categorize the following news article into one of these categories: "
                "Sports, Entertainment, Politics, International, or Others. "
                "Respond with only the category name.\n\n"
                f"Title: {title}\n\n"
                f"Content: {content[:500]}..."  # Using first 500 characters of content
            )
            response = model.generate_content(prompt)
            category = response.text.strip()

            # Ensure the category is one of the expected ones
            valid_categories = ['Sports', 'Entertainment', 'Politics', 'International', 'Others']
            return category if category in valid_categories else 'Others'

        except Exception as e:
            print(f"Error in categorization: {str(e)}")
            if attempt < max_attempts:
                print(f"Retrying attempt {attempt + 1}...")
                time.sleep(1)
            else:
                print(f"Maximum retry attempts reached. Unable to categorize.")
                return 'Others'

def read_opml_file():
    with open("news-links.opml", "r", encoding='utf-8') as opml_file:
        soup = BeautifulSoup(opml_file.read(), "lxml-xml")
        feed_urls = [outline.get("xmlUrl") for outline in soup.find_all("outline") if outline.get("xmlUrl")]
    return feed_urls

def ai_summarizer(news_info):
    max_attempts = 7
    model = genai.GenerativeModel('gemini-pro')

    for attempt in range(1, max_attempts + 1):
        try:
            prompt = (
                "You are a person working at a news agency or newspaper printing press, "
                "your task is to summarize the given news articles in at most 100 words and give it in form of bullet points:\n\n"
                f"{news_info}"
            )
            response = model.generate_content(prompt)
            print(response)
            return response.text
        except Exception as e:
            print(f"Error: {str(e)}")
            if attempt < max_attempts:
                print(f"Retrying attempt {attempt + 1}...")
                time.sleep(1)
            else:
                print(f"Maximum retry attempts reached. Unable to summarize.")
                break

def sqlite_data(post):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()

    # Check if the category column exists, if not, add it
    cursor.execute("PRAGMA table_info(rss_feed)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'category' not in columns:
        cursor.execute("ALTER TABLE rss_feed ADD COLUMN category TEXT")
        conn.commit()

    cursor.execute('''CREATE TABLE IF NOT EXISTS rss_feed
                    (date TEXT, title TEXT, full_content TEXT, summarized_content TEXT, link TEXT, author TEXT, category TEXT)''')

    cursor.execute("SELECT * FROM rss_feed WHERE title = ? AND link = ?",
                   (post['title'], post['link']))
    existing_record = cursor.fetchone()

    if existing_record:
        print("Duplicate data. Not saved.")
    else:
        cursor.execute("INSERT INTO rss_feed VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (post['published'], post['title'], post['full_content'], post['summarized_content'], post['link'],
                        post['author'], post.get('category', 'Uncategorized')))
        conn.commit()
        print("Data Saved Successfully.")
        print("------------------------------------------------------------")

    conn.close()
def sort_data_by_date(data_list):
    sorted_data = sorted(data_list, key=lambda x: x['date'], reverse=True)
    return sorted_data

def remove_blank_lines(_full_content):
    return re.sub(r'^\s*\n', '', _full_content, flags=re.MULTILINE)

def article_info(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        html = response.text
        title, content = article_parser.parse(url=url, html=html, output='markdown', timeout=5)
        return content

    except requests.exceptions.RequestException as e:
        print(f"Error fetching the article: {e}")
        return ""

def parse_rss_feed(url):
    print("Trying to fetch rss feeds.")
    feed = feedparser.parse(url)
    posts = []

    for post in feed.entries:
        post_url = post.link
        print(post_url)

        existing_post = check_existing_post(post.title, post_url)

        if existing_post:
            print("Post already exists. Skipping.")
            print("------------------------------------------------------------")
            posts.append(existing_post)

        else:
            full_content = article_info(post_url)
            full_content = remove_blank_lines(full_content)
            summarized_content = ai_summarizer(full_content)
            if 'published' in post:
                published_date = parse(post.published)
            else:
                published_date = None

            if 'author' in post:
                author = post.author
            else:
                author = "Not mentioned"

            category = categorize_article(post.title, full_content)

            post_data = {
                'title': post.title,
                'author': author,
                'published': published_date,
                'link': post_url,
                'full_content': full_content,
                'summarized_content': summarized_content,
                'category': category
            }

            posts.append(post_data)
            sqlite_data(post_data)

    return posts


def check_existing_post(title, link):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()

    # Check if the category column exists, if not, add it
    cursor.execute("PRAGMA table_info(rss_feed)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'category' not in columns:
        cursor.execute("ALTER TABLE rss_feed ADD COLUMN category TEXT")
        conn.commit()

    cursor.execute('''CREATE TABLE IF NOT EXISTS rss_feed
                    (date TEXT, title TEXT, full_content TEXT, summarized_content TEXT, link TEXT, author TEXT, category TEXT)''')
    cursor.execute("SELECT * FROM rss_feed WHERE title = ? AND link = ?", (title, link))
    existing_record = cursor.fetchone()

    conn.close()

    if existing_record:
        return {
            'title': existing_record[1],
            'author': existing_record[5],
            'published': existing_record[0],
            'link': existing_record[4],
            'full_content': existing_record[2],
            'category': existing_record[6] if len(existing_record) > 6 else 'Uncategorized'
        }
    else:
        return None
app = Flask(__name__)

def get_data(sort_order, category=None):
    data_list = []
    sorted_data_by_date = []

    try:
        conn = sqlite3.connect('summarizer-data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rss_feed')
        data = cursor.fetchall()

        for row in data:
            full_content = markdown2.markdown(row[2], extras=["markdown-urls"])
            summarized_content = markdown2.markdown(row[3] if row[3] is not None else "", extras=["markdown-urls"])
            date_time = datetime.fromisoformat(row[0])
            date_iso = date_time.isoformat()

            data_dict = {
                'date': date_iso,
                'title': row[1],
                'full_content': full_content,
                'summarized_content': summarized_content,
                'link': row[4],
                'author': row[5],
                'category': row[6] if len(row) > 6 else 'Uncategorized'  # Add this line
            }

            data_list.append(data_dict)

        if category and category != 'All':
            data_list = [item for item in data_list if item['category'] == category]

        if sort_order == 'desc':
            sorted_data_by_date = sorted(data_list, key=lambda x: x['date'], reverse=True)
        else:
            sorted_data_by_date = sorted(data_list, key=lambda x: x['date'], reverse=False)

        conn.close()
    except sqlite3.OperationalError as e:
        print("Database error:", str(e))
    except Exception as e:
        print("An error occurred:", str(e))

    return sorted_data_by_date
def format_datetime(dateTimeString):
    date = datetime.fromisoformat(dateTimeString)
    formatted_date = date.strftime("%A, %B %d, %Y %I:%M %p")
    return formatted_date

@app.route('/', methods=['GET', 'POST'])
def index():
    sort_order = 'desc'
    category = 'All'
    if request.method == 'POST':
        sort_order = request.form.get('sortorder')
        category = request.form.get('category')
    data = get_data(sort_order, category)

    categories = ['All', 'Sports', 'Entertainment', 'Politics', 'International', 'Others']
    return render_template('index.html', data=data, formatDateTime=format_datetime, categories=categories, selected_category=category)

@app.route('/summarize', methods=['GET'])
def main():
    urls = read_opml_file()
    for url in urls:
        print("Processing URL:", url)
        parse_rss_feed(url)

    return redirect("/")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)