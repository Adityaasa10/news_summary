# summarizer.py with Hugging Face + Pinecone + RAG integration (using sentence-transformers/all-MiniLM-L6-v2)

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
import random
import hashlib
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

# Load environment variables
load_dotenv()

HF_API_KEY = os.getenv("HF_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "newssummary")
PINECONE_HOST = os.getenv("PINECONE_HOST")

# Initialize Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)

# Ensure index has correct dimension (384)
if PINECONE_INDEX not in pc.list_indexes().names():
    pc.create_index(
        name=PINECONE_INDEX,
        dimension=384,
        metric="cosine",
        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}}
    )
pinecone_index = pc.Index(PINECONE_INDEX, host=PINECONE_HOST)


# Load embedding model: sentence-transformers/all-MiniLM-L6-v2
embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Embedding function
def generate_embedding(text):
    return embedder.encode(text, convert_to_numpy=True).tolist()

app = Flask(__name__)

# --- Utility Functions ---

def categorize_article(title, content):
    keywords = {
        'Sports': ['sport', 'game', 'player', 'team', 'match'],
        'Entertainment': ['movie', 'music', 'celebrity', 'film', 'star'],
        'Politics': ['government', 'election', 'president', 'policy', 'minister'],
        'International': ['global', 'world', 'foreign', 'international', 'abroad']
    }
    text = (title + ' ' + content).lower()
    for category, words in keywords.items():
        if any(word in text for word in words):
            return category
    return 'Others'

def read_opml_file():
    with open("news-links.opml", "r", encoding='utf-8') as opml_file:
        soup = BeautifulSoup(opml_file.read(), "lxml-xml")
        return [outline.get("xmlUrl") for outline in soup.find_all("outline") if outline.get("xmlUrl")]

def ai_summarizer(news_info):
    endpoint = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    data = {
        "inputs": news_info,
        "parameters": {"max_length": 130, "min_length": 30, "do_sample": False}
    }
    try:
        res = requests.post(endpoint, headers=headers, json=data)
        res.raise_for_status()
        return res.json()[0]['summary_text']
    except Exception as e:
        print(f"Summarization failed: {e}")
        return ""

def is_similar(summary, threshold=0.9):
    vec = generate_embedding(summary)
    res = pinecone_index.query(vector=vec, top_k=1, include_metadata=True)
    return res.matches and res.matches[0].score > threshold

def save_to_pinecone(summary, metadata):
    vec = generate_embedding(summary)
    pinecone_index.upsert([(metadata["id"], vec, metadata)])

def sqlite_data(post):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS rss_feed
                      (date TEXT, title TEXT, full_content TEXT, summarized_content TEXT, link TEXT, author TEXT, category TEXT)''')
    cursor.execute("SELECT * FROM rss_feed WHERE title = ? AND link = ?", (post['title'], post['link']))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO rss_feed VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (post['published'], post['title'], post['full_content'], post['summarized_content'],
                        post['link'], post['author'], post['category']))
        conn.commit()
    conn.close()

def remove_blank_lines(content):
    return re.sub(r'^\s*\n', '', content, flags=re.MULTILINE)

def article_info(url):
    try:
        html = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).text
        _, content = article_parser.parse(url=url, html=html, output='markdown', timeout=5)
        return content
    except Exception as e:
        print(f"Error fetching article: {e}")
        return ""

def parse_rss_feed(url):
    print("Fetching RSS feed:", url)
    feed = feedparser.parse(url)
    for post in feed.entries:
        post_url = post.link
        title = post.title
        published_date = parse(post.published) if 'published' in post else None
        author = post.author if 'author' in post else "Not mentioned"
        full_content = remove_blank_lines(article_info(post_url))
        summary = ai_summarizer(full_content)

        if is_similar(summary):
            print("Skipped similar summary.")
            continue

        category = categorize_article(title, full_content)
        post_data = {
            'title': title,
            'author': author,
            'published': published_date,
            'link': post_url,
            'full_content': full_content,
            'summarized_content': summary,
            'category': category
        }

        sqlite_data(post_data)
        save_to_pinecone(summary, {"id": hashlib.md5(summary.encode()).hexdigest(), "title": title})

def get_data(sort_order, category=None, date=None):
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()
    if date:
        cursor.execute('SELECT * FROM rss_feed WHERE date(date) = ?', (date,))
    else:
        cursor.execute('SELECT * FROM rss_feed')
    rows = cursor.fetchall()
    conn.close()

    data_list = []
    for row in rows:
        full = markdown2.markdown(row[2], extras=["markdown-urls"])
        summary = markdown2.markdown(row[3] or '', extras=["markdown-urls"])
        date_time = datetime.fromisoformat(row[0])
        data_list.append({
            'date': date_time.isoformat(),
            'title': row[1],
            'full_content': full,
            'summarized_content': summary,
            'link': row[4],
            'author': row[5],
            'category': row[6] or 'Uncategorized'
        })

    if category and category != 'All':
        data_list = [d for d in data_list if d['category'] == category]

    return sorted(data_list, key=lambda x: x['date'], reverse=(sort_order == 'desc'))

def format_datetime(dateTimeString):
    return datetime.fromisoformat(dateTimeString).strftime("%A, %B %d, %Y %I:%M %p")

# --- Routes ---

@app.route('/', methods=['GET', 'POST'])
def home():
    sort_order = request.form.get('sortorder', 'desc')
    category = request.form.get('category', 'All')
    data = get_data(sort_order, category)
    categories = ['All', 'Sports', 'Entertainment', 'Politics', 'International', 'Others']
    return render_template('index.html', data=data, formatDateTime=format_datetime, categories=categories, selected_category=category)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '')
    conn = sqlite3.connect('summarizer-data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rss_feed WHERE title LIKE ? OR full_content LIKE ?", (f"%{query}%", f"%{query}%"))
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append({
            'date': datetime.fromisoformat(row[0]).isoformat(),
            'title': row[1],
            'full_content': markdown2.markdown(row[2], extras=["markdown-urls"]),
            'summarized_content': markdown2.markdown(row[3], extras=["markdown-urls"]),
            'link': row[4],
            'author': row[5]
        })
    return render_template('search_results.html', query=query, results=results, formatDateTime=format_datetime)

@app.route('/summarize', methods=['GET'])
def summarize():
    for url in read_opml_file():
        parse_rss_feed(url)
    return redirect("/")

@app.route('/filter_by_date', methods=['GET', 'POST'])
def filter_by_date():
    sort_order = request.form.get('sortorder', 'desc')
    category = request.form.get('category', 'All')
    date = request.form.get('date')
    data = get_data(sort_order, category, date) if date else []
    categories = ['All', 'Sports', 'Entertainment', 'Politics', 'International', 'Others']
    return render_template('filter_by_date.html', data=data, formatDateTime=format_datetime, categories=categories, selected_category=category, selected_date=date, selected_sort_order=sort_order)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
