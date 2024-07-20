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

# Load environment variables
load_dotenv()
api_key = os.getenv("API_KEY")
genai.configure(api_key=api_key)

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
                f"Content: {content[:500]}..."
            )
            response = model.generate_content(prompt)
            category = response.text.strip()
            valid_categories = ['Sports', 'Entertainment', 'Politics', 'International', 'Others']
            return category if category in valid_categories else 'Others'
        except Exception as e:
            print(f"Error in categorization: {str(e)}")
            if attempt < max_attempts:
                print(f"Retrying attempt {attempt + 1}...")
                time.sleep(1)
            else:
                print("Maximum retry attempts reached. Unable to categorize.")
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
                "your task is to summarize the given news articles in at most 100 words and give it in the form of bullet points:\n\n"
                f"{news_info}"
            )
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error: {str(e)}")
            if attempt < max_attempts:
                print(f"Retrying attempt {attempt + 1}...")
                time.sleep(1)
            else:
                print("Maximum retry attempts reached. Unable to summarize.")
                return ""

def sqlite_data(post):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()

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

    conn.close()

def sort_data_by_date(data_list, sort_order):
    return sorted(data_list, key=lambda x: x['date'], reverse=(sort_order == 'desc'))

def remove_blank_lines(content):
    return re.sub(r'^\s*\n', '', content, flags=re.MULTILINE)

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
    print("Fetching RSS feeds.")
    feed = feedparser.parse(url)
    posts = []

    for post in feed.entries:
        post_url = post.link
        print(post_url)

        existing_post = check_existing_post(post.title, post_url)
        if existing_post:
            print("Post already exists. Skipping.")
            posts.append(existing_post)
            continue

        full_content = article_info(post_url)
        full_content = remove_blank_lines(full_content)
        summarized_content = ai_summarizer(full_content)
        published_date = parse(post.published) if 'published' in post else None
        author = post.author if 'author' in post else "Not mentioned"
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
    return None

app = Flask(__name__)

def get_data(sort_order, category=None):
    data_list = []
    try:
        conn = sqlite3.connect('summarizer-data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rss_feed')
        data = cursor.fetchall()

        for row in data:
            full_content = markdown2.markdown(row[2], extras=["markdown-urls"])
            summarized_content = markdown2.markdown(row[3] if row[3] else "", extras=["markdown-urls"])
            date_time = datetime.fromisoformat(row[0])
            date_iso = date_time.isoformat()

            data_dict = {
                'date': date_iso,
                'title': row[1],
                'full_content': full_content,
                'summarized_content': summarized_content,
                'link': row[4],
                'author': row[5],
                'category': row[6] if len(row) > 6 else 'Uncategorized'
            }
            data_list.append(data_dict)

        if category and category != 'All':
            data_list = [item for item in data_list if item['category'] == category]

        conn.close()
    except sqlite3.OperationalError as e:
        print("Database error:", str(e))
    except Exception as e:
        print("An error occurred:", str(e))

    return sort_data_by_date(data_list, sort_order)

def format_datetime(dateTimeString):
    date = datetime.fromisoformat(dateTimeString)
    return date.strftime("%A, %B %d, %Y %I:%M %p")

@app.route('/', methods=['GET', 'POST'])
def index():
    sort_order = 'desc'
    category = 'All'
    data = []

    if request.method == 'POST':
        sort_order = request.form.get('sortorder', 'desc')
        category = request.form.get('category', 'All')
        data = get_data(sort_order, category)
    else:
        data = []

    categories = ['All', 'Sports', 'Entertainment', 'Politics', 'International', 'Others']
    return render_template('index.html', data=data, formatDateTime=format_datetime, categories=categories, selected_category=category)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '')
    search_results = []

    try:
        conn = sqlite3.connect('summarizer-data.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rss_feed WHERE title LIKE ? OR full_content LIKE ?", ('%'+query+'%', '%'+query+'%'))
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

            search_results.append(data_dict)

        conn.close()
    except sqlite3.OperationalError as e:
        print("Database file not found. Running without it.")

    return render_template('search_results.html', query=query, results=search_results, formatDateTime=format_datetime)


@app.route('/summarize', methods=['GET'])
def summarize():
    urls = read_opml_file()
    for url in urls:
        print("Processing URL:", url)
        parse_rss_feed(url)
    return redirect("/")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)