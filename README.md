This repository contains a Python Flask web application for fetching and summarizing news articles from RSS feeds.

## Features

1. *RSS Feed Parsing*: It fetches news articles from RSS feeds using the feedparser library.

2. *Article Content Extraction*: It extracts the full content of each article from the web pages using the requests library.

3. *Text Summarization*: It summarizes the extracted article content using the Gemini API.

4. *Database Storage*: It stores the article details, including the title, author, publication date, link, full content, and summarized content, in a SQLite database.

5. *Web Interface*: It offers a web interface using Flask, allowing users to view and interact with the collected news articles. It offers Light and Dark Themes and Custom Themes.

  

## Getting Started

To run this application locally, follow these steps:

Clone this repository to your local machine or download the zip file and extract it to your preferred location.

 bash
git clone https://github.com/Adityaasa10/news_summary.git


Install the required Python libraries by running:

 bash
pip install -r requirements.txt


Create .env file in root directory of your project folder
and add this 

API_KEY=YOUR-API-KEY


Obtain a Cohere API key and replace "YOUR-API-KEY" in the code with your actual API key.

Prepare an OPML file (e.g., "news_links.opml") with the RSS feed URLs you want to fetch articles from.
Run the Flask application:

 bash
python summarizer.py


The application should now be accessible locally in your web browser.

## Usage

Start the application as described in the "Getting Started" section.

Access the web interface by navigating to http://localhost:5000/ or http://127.0.0.1:5000 in your web browser.

The application will fetch articles from the RSS feeds specified in the "news_links.opml" file and display them on the web page.

Enjoy your News Summaries.

## Dependencies

The project uses the following Python libraries and APIs:

- feedparser for parsing RSS feeds.

- requests for making HTTP requests to fetch article content.

- cohere for text summarization.

- sqlite3 for database management.

- beautifulsoup4 for parsing HTML content.

- markdown2 for rendering Markdown content.

- Flask for the web application.

Make sure to install these dependencies as mentioned in the "Getting Started" section.

## Contributing

If you'd like to contribute to this project, please fork the repository and create a pull request. We welcome improvements, bug fixes, and feature additions.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.
