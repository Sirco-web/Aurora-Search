# Sloth Search - A Google-like Search Engine Clone

Sloth Search is a project that aims to recreate Google, including crawling, indexing, and serving results through a user-friendly front-end interface. The project consists of three main components: the Client, Search, and Server.
[Check out the video for a full explanation here](https://youtu.be/WCpimlH0Kck?si=_zFzrb1cxZinWKo3)

## Project Structure

The project is divided into the following folders:

- **Client**: Contains the front-end code, providing a user interface similar to Google search, where users can enter queries and view search results.

- **Search**: Contains the core components of Sloth Search, which replicate the three main parts of Google:

  - **Crawling**: The web crawler that collects information from the web.

  - **Indexing**: Processing and storing the content collected by the crawler for efficient searching.

  - **Serving (PageRank)**: Serving search results based on their relevance and PageRank algorithm.

- **Server**: Contains the search API used to handle client requests and provide search results.

## Installation and Setup

**1. Clone the Repository**

```sh
git clone https://github.com/The-CodingSloth/sloth-search.git
cd sloth-search
```

**2. Install the necessary Python dependencies**

```sh
pip install -r requirements.txt
```

**3. Client Setup**

- The client contains the HTML, CSS, and JavaScript code to run the front-end.

- Open the `index.html` file in your browser, or use a static file server to serve the client code locally.

- You can also use the live server extension.

**4. Search Setup**
  
- The `search` directory contains the code for crawling, indexing, and serving.

- You can start the process by running:

```sh
python search/complete_examples/advanced_pagerank.py
```

- This will crawl, index, and prepare the content for searching.

- If you want to run any other files, do the same process:

```sh
python search/<path to file you want to run>
```

## How It Works

**1. Crawling**

- The crawler starts with a set of seed URLs and collects links and content from the web.

- It respects `robots.txt` to avoid being blocked and to ensure ethical crawling.

- Parsed data is stored in a format ready for indexing.

**2. Indexing**

- The indexing module processes the crawled pages.

- The content is tokenized, cleaned, stemmed, and stop words are removed using the NLTK library.

- The resulting indexed data is saved to be used by the search API.

**3. Serving and PageRank**

- The PageRank algorithm is used to rank pages based on their importance.

- When a user searches for a query through the client, the server uses the indexed data and PageRank scores to return the most relevant pages.

## Important Notes

- **Respecting Websites**: The crawler respects `robots.txt` rules. Please make sure not to overload any websites.

- **PageRank Algorithm**: The implementation of the PageRank algorithm uses an iterative approach to rank pages based on the links.

- **Data Storage**: The crawler and indexer use CSV files for data storage (`advanced_pagerank_inverted_index.csv` and `advanced_pagerank.csv`). Make sure these files are writable during execution.

## Contributing

Contributions are welcome! If you'd like to contribute to the development of Sloth Search, feel free to fork the repository, make changes, and submit a pull request.

## License

This project is open-source and available under the MIT License.

If you have any questions or suggestions, feel free to contact me.

Happy Searching with Sloth Search! 🦥🔍
