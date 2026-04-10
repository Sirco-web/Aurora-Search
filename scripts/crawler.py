import argparse
import configparser
import gzip
import hashlib
import io
import json
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, PriorityQueue
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

# Disable SSL verification warnings for public web crawling
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if __package__:
    from .indexing import index_page
    from .pagerank import compute_pagerank
    from .panda import score_content_quality
    from .penguin import score_link_quality
else:
    from indexing import index_page
    from pagerank import compute_pagerank
    from panda import score_content_quality
    from penguin import score_link_quality

DEFAULT_STARTING_URLS = [
    # Wikipedia - tons of content, highly structured
    "https://en.wikipedia.org/wiki/Main_Page",
    "https://en.wikipedia.org/wiki/Special:Random",  # Random articles = diverse content
    "https://en.wikipedia.org/w/api.php?action=query&list=random&rnnamespace=0&rnlimit=50&format=json",
    
    # Reddit - real user discussions about everything
    "https://www.reddit.com/r/explainlikeimfive/",
    "https://www.reddit.com/r/todayilearned/",
    "https://www.reddit.com/r/AskReddit/",
    "https://www.reddit.com/r/science/",
    "https://www.reddit.com/r/technology/",
    "https://www.reddit.com/r/news/",
    "https://www.reddit.com/r/worldnews/",
    "https://www.reddit.com/r/food/",  # For "egg" queries!
    "https://www.reddit.com/r/recipes/",
    "https://www.reddit.com/r/cooking/",
    
    # News with search/topic pages
    "https://www.bbc.com/news",
    "https://www.bbc.com/news/world",
    "https://www.bbc.com/news/business",
    "https://www.cnn.com/world",
    "https://www.cnn.com/us",
    "https://www.nytimes.com/section/world",
    "https://www.theguardian.com/world",
    
    # Knowledge bases with deep content
    "https://stackoverflow.com/questions/tagged/javascript",
    "https://stackoverflow.com/questions/tagged/python",
    "https://stackoverflow.com/questions/tagged/web-development",
    "https://superuser.com/questions/tagged/windows",
    "https://serverfault.com/questions/tagged/linux",
    "https://dev.to/top/week",
    "https://medium.com/tag/technology",
    "https://medium.com/tag/science",
    
    # Reference & Learning
    "https://www.britannica.com/browse",
    "https://www.khanacademy.org/",
    "https://plato.stanford.edu/",
    "https://www.coursera.org/",
    
    # Tech & Development
    "https://github.com/trending",
    "https://github.com/topics",
    "https://news.ycombinator.com/newest",
    "https://news.ycombinator.com/best",
    
    # Q&A Sites
    "https://www.quora.com/",
    "https://stackexchange.com/sites",
    
    # Food/Cooking (for diverse content including "egg" queries)
    "https://www.allrecipes.com/",
    "https://www.foodnetwork.com/recipes",
    "https://www.bonappetitmag.com/recipes",
    "https://www.seriouseats.com/recipes",
    
    # Shopping/Product Info
    "https://www.amazon.com/s?k=products&page=1",
    "https://www.ebay.com/sch/i.html?",
    
    # Travel & Local
    "https://www.tripadvisor.com/Attractions",
    "https://www.yelp.com/search?find_desc=restaurants",
    
    # Video platforms for transcripts/descriptions
    "https://www.youtube.com/feed/trending",
    
    # Academic/Research
    "https://arxiv.org/list/cs/recent",
    "https://scholar.google.com/",
    
    # News aggregators
    "https://apnews.com/hub/",
    "https://www.reuters.com/world",
    "https://www.aljazeera.com/news",
    "https://www.npr.org/sections/news/",
    
    # Government & Data sources
    "https://www.usa.gov",
    "https://www.data.gov",
    "https://www.nasa.gov",
    "https://www.census.gov",
    "https://www.loc.gov",
    
    # International sites & languages
    "https://www.bbc.co.uk",
    "https://www.lemonde.fr",
    "https://www.spiegel.de",
    "https://substack.com",
    
    # More Reddit for diverse topics
    "https://www.reddit.com/r/all",
    "https://www.reddit.com/r/gaming/",
    "https://www.reddit.com/r/videogames/",
    "https://www.reddit.com/r/pcgaming/",
    "https://www.reddit.com/r/games/",
    
    # Gaming & Entertainment (Expanded)
    "https://www.polygon.com/",
    "https://www.polygon.com/reviews",
    "https://www.polygon.com/news",
    "https://www.ign.com/",
    "https://www.ign.com/reviews",
    "https://www.ign.com/news",
    "https://www.gamespot.com/",
    "https://www.gamespot.com/reviews",
    "https://www.metacritic.com/",
    "https://www.rockpapershotgun.com/",
    "https://www.thegamer.com/",
    "https://www.imdb.com/",
    "https://www.rottentomatoes.com/",
    "https://www.pitchfork.com/",
    "https://www.theonion.com/",
    "https://www.vulture.com/",
    
    # Wikipedia - Expanded with many portals and categories
    "https://en.wikipedia.org/wiki/Portal:Technology",
    "https://en.wikipedia.org/wiki/Portal:Science",
    "https://en.wikipedia.org/wiki/Portal:History",
    "https://en.wikipedia.org/wiki/Portal:Society",
    "https://en.wikipedia.org/wiki/Portal:Arts",
    "https://en.wikipedia.org/wiki/Portal:Geography",
    "https://en.wikipedia.org/wiki/Portal:Health",
    "https://en.wikipedia.org/wiki/Portal:Sports",
    "https://en.wikipedia.org/wiki/Portal:Mathematics",
    "https://en.wikipedia.org/wiki/Portal:Physics",
    "https://en.wikipedia.org/wiki/Portal:Chemistry",
    "https://en.wikipedia.org/wiki/Portal:Biology",
    "https://en.wikipedia.org/wiki/Category:Stub_articles",
    "https://en.wikipedia.org/wiki/Wikipedia:Featured_articles",
    "https://en.wikipedia.org/wiki/Wikipedia:Good_articles",
    "https://en.wikipedia.org/wiki/Category:Computer_science",
    "https://en.wikipedia.org/wiki/Category:Engineering",
    "https://en.wikipedia.org/wiki/Category:Mathematics",
    "https://en.wikipedia.org/wiki/Category:Medicine",
    "https://en.wikipedia.org/wiki/Category:Business",
    "https://en.wikipedia.org/wiki/Category:Economics",
    "https://en.wikipedia.org/wiki/Category:Technology",
    "https://en.wikipedia.org/wiki/Category:Internet",
    "https://en.wikipedia.org/wiki/Category:Video_games",
    "https://en.wikipedia.org/wiki/Category:Films",
    "https://en.wikipedia.org/wiki/Category:Music",
    "https://en.wikipedia.org/wiki/Category:Literature",
    
    # Additional Knowledge & Learning
    "https://www.edx.org/",
    "https://www.udemy.com/",
    "https://www.linkedin.com/learning/",
    "https://www.skillshare.com/",
    
    # Additional News & Current Events
    "https://www.washingtonpost.com/",
    "https://www.businessinsider.com/",
    "https://www.forbes.com/",
    "https://www.cnbc.com/",
    "https://finance.yahoo.com/",
    
    # Science & Research (Expanded)
    "https://www.pubmed.ncbi.nlm.nih.gov/",
    "https://www.sciencedirect.com/",
    "https://www.nature.com/",
    "https://www.doi.org/",
    "https://www.jstor.org/",
    
    # Sports & Recreation
    "https://www.espn.com/",
    "https://www.sports-reference.com/",
    "https://www.bleacherreport.com/",
    
    # Travel & Local
    "https://www.tripadvisor.com/",
    "https://www.yelp.com/",
    "https://www.booking.com/",
    
    # Shopping & Products
    "https://www.amazon.com/",
    "https://www.ebay.com/",
    
    # Entertainment & Streaming
    "https://www.youtube.com/feed/trending",
    "https://www.youtube.com/results?search_query=technology",
    "https://www.twitch.tv/",
    
    # International & Language Diversity
    "https://www.washingtonpost.com/",
    "https://www.theguardian.com/",
    
    # More Technology & Open Source
    "https://www.python.org/",
    "https://www.rust-lang.org/",
    "https://go.dev/",
    "https://nodejs.org/",
    "https://www.djangoproject.com/",
    "https://flask.palletsprojects.com/",
    "https://www.tensorflow.org/",
    "https://pytorch.org/",
    "https://keras.io/",
    "https://scikit-learn.org/",
    
    # Data Science & ML
    "https://www.kaggle.com/",
    "https://colab.research.google.com/",
    "https://jupyter.org/",
    "https://www.dataquest.io/",
    "https://www.datacamp.com/",
    "https://towards-data-science.medium.com/",
    
    # Web Development
    "https://www.w3schools.com/",
    "https://developer.mozilla.org/",
    "https://caniuse.com/",
    "https://html.spec.whatwg.org/",
    "https://www.ecma-international.org/",
    "https://react.dev/",
    "https://vuejs.org/",
    "https://angular.io/",
    "https://svelte.dev/",
    
    # Cloud & Infrastructure
    "https://aws.amazon.com/",
    "https://cloud.google.com/",
    "https://azure.microsoft.com/",
    "https://www.digitalocean.com/",
    "https://www.heroku.com/",
    "https://vercel.com/",
    "https://www.docker.com/",
    "https://kubernetes.io/",
    
    # Security & Privacy
    "https://owasp.org/",
    "https://www.eff.org/",
    "https://cve.mitre.org/",
    "https://www.cisa.gov/",
    "https://www.apple.com/privacy/",
    "https://www.mozilla.org/privacy/",
    
    # Design & UX
    "https://www.figma.com/",
    "https://dribbble.com/",
    "https://www.behance.net/",
    "https://www.designthinking.ideo.com/",
    "https://www.awwwards.com/",
    
    # Product & Startup
    "https://www.producthunt.com/",
    "https://www.indiehackers.com/",
    "https://www.ycombinator.com/",
    "https://www.techcrunch.com/",
    "https://venturebeat.com/",
    "https://www.theinformation.com/",
    
    # AI & Machine Learning News
    "https://www.openai.com/",
    "https://deepmind.google/",
    "https://research.meta.com/",
    "https://www.anthropic.com/",
    "https://www.mistral.ai/",
    
    # Cybersecurity
    "https://www.darknet.live/",
    "https://www.bleepingcomputer.com/",
    "https://www.securityweek.com/",
    "https://www.infosecurity-magazine.com/",
    "https://www.tripwire.com/",
    
    # Physics & Science News
    "https://arxiv.org/recent",
    "https://phys.org/",
    "https://www.sciencedaily.com/",
    "https://www.scientificamerican.com/",
    "https://www.newscientist.com/",
    
    # History & Culture
    "https://www.history.com/",
    "https://www.historytoday.com/",
    "https://www.smithsonianmag.com/",
    "https://www.theatlanticwire.com/",
    "https://hyperallergic.com/",
    
    # Philosophy & Ideas
    "https://www.philosophersnews.com/",
    "https://plato.stanford.edu/entries/",
    "https://iep.utm.edu/",
    "https://www.dialectica.org/",
    
    # Mathematics
    "https://www.mathworld.wolfram.com/",
    "https://proofwiki.org/",
    "https://www.artofproblemsolving.com/",
    "https://math.stackexchange.com/",
    "https://www.aops.com/",
    
    # Astronomy & Space
    "https://www.nasa.gov/",
    "https://www.nasa.gov/mission_pages/",
    "https://www.esa.int/",
    "https://www.spacex.com/",
    "https://www.isro.gov.in/",
    "https://www.astronomy.com/",
    
    # Biology & Medicine
    "https://www.ncbi.nlm.nih.gov/",
    "https://www.medline.nih.gov/",
    "https://www.healthline.com/",
    "https://www.webmd.com/",
    "https://www.verywellhealth.com/",
    
    # Climate & Environment
    "https://www.ipcc.ch/",
    "https://climate.nasa.gov/",
    "https://www.epa.gov/climate",
    "https://www.greenpeace.org/",
    "https://www.worldwildlife.org/",
    
    # Economics & Markets
    "https://www.imf.org/",
    "https://www.worldbank.org/",
    "https://www.oecd.org/",
    "https://markets.businessinsider.com/",
    "https://www.investing.com/",
    
    # Programming Languages
    "https://www.typescriptlang.org/",
    "https://www.lua.org/",
    "https://www.ruby-lang.org/",
    "https://www.php.net/",
    "https://www.swift.org/",
    "https://kotlinlang.org/",
    "https://www.scala-lang.org/",
    "https://www.haskell.org/",
    
    # Mobile Development
    "https://developer.android.com/",
    "https://developer.apple.com/",
    "https://flutter.dev/",
    "https://reactnative.dev/",
    "https://www.xamarin.com/",
    
    # Databases
    "https://www.postgresql.org/",
    "https://www.mysql.com/",
    "https://www.mongodb.com/",
    "https://redis.io/",
    "https://www.elastic.co/",
    "https://cassandra.apache.org/",
    
    # DevOps & Monitoring
    "https://prometheus.io/",
    "https://www.elastic.co/products/kibana",
    "https://grafana.com/",
    "https://www.splunk.com/",
    "https://www.datadog.com/",
    
    # Version Control
    "https://www.mercurial-scm.org/",
    "https://www.perforce.com/",
    "https://www.fossil-scm.org/",
    
    # Documentation & Writing
    "https://www.sphinx-doc.org/",
    "https://swagger.io/",
    "https://www.gitbook.com/",
    "https://www.mkdocs.org/",
    
    # Project Management
    "https://www.atlassian.com/",
    "https://www.trello.com/",
    "https://www.asana.com/",
    "https://www.monday.com/",
    "https://www.notion.so/",
    
    # Community & Social
    "https://www.slashdot.org/",
    "https://www.digg.com/",
    "https://www.boingboing.net/",
    "https://www.metafilter.com/",
    "https://www.vpnsecure.me/",
    
    # TECH COMPANIES - Direct Wikipedia Articles
    "https://en.wikipedia.org/wiki/Google",
    "https://en.wikipedia.org/wiki/Apple_Inc.",
    "https://en.wikipedia.org/wiki/Microsoft",
    "https://en.wikipedia.org/wiki/Amazon_(company)",
    "https://en.wikipedia.org/wiki/Meta_Platforms",
    "https://en.wikipedia.org/wiki/Tesla_Inc.",
    "https://en.wikipedia.org/wiki/Twitter",
    "https://en.wikipedia.org/wiki/Netflix",
    "https://en.wikipedia.org/wiki/Nvidia",
    "https://en.wikipedia.org/wiki/Intel",
    "https://en.wikipedia.org/wiki/Oracle_Corporation",
    "https://en.wikipedia.org/wiki/IBM",
    "https://en.wikipedia.org/wiki/Cisco_Systems",
    "https://en.wikipedia.org/wiki/Salesforce",
    "https://en.wikipedia.org/wiki/Zoom_Video_Communications",
    "https://en.wikipedia.org/wiki/ByteDance",
    "https://en.wikipedia.org/wiki/Alibaba_Group",
    "https://en.wikipedia.org/wiki/Tencent",
    "https://en.wikipedia.org/wiki/Uber",
    "https://en.wikipedia.org/wiki/Airbnb",
    
    # IMPORTANT CONCEPTS & ENTITIES
    "https://en.wikipedia.org/wiki/Internet",
    "https://en.wikipedia.org/wiki/World_Wide_Web",
    "https://en.wikipedia.org/wiki/Computer",
    "https://en.wikipedia.org/wiki/Artificial_intelligence",
    "https://en.wikipedia.org/wiki/Machine_learning",
    "https://en.wikipedia.org/wiki/Blockchain",
    "https://en.wikipedia.org/wiki/Cryptocurrency",
    "https://en.wikipedia.org/wiki/Bitcoin",
    "https://en.wikipedia.org/wiki/Quantum_computing",
    "https://en.wikipedia.org/wiki/Electric_vehicle",
    "https://en.wikipedia.org/wiki/Renewable_energy",
    "https://en.wikipedia.org/wiki/Climate_change",
    "https://en.wikipedia.org/wiki/Pandemic",
    "https://en.wikipedia.org/wiki/Vaccine",
    "https://en.wikipedia.org/wiki/DNA",
    "https://en.wikipedia.org/wiki/Gene_therapy",
    "https://en.wikipedia.org/wiki/Nanotechnology",
    "https://en.wikipedia.org/wiki/Space_exploration",
    "https://en.wikipedia.org/wiki/Black_hole",
    "https://en.wikipedia.org/wiki/Gravitational_wave",
    
    # LISTS & CATEGORIES FOR DIVERSE CONTENT
    "https://en.wikipedia.org/wiki/Lists_of_countries_and_territories",
    "https://en.wikipedia.org/wiki/List_of_countries_by_population",
    "https://en.wikipedia.org/wiki/List_of_countries_by_area",
    "https://en.wikipedia.org/wiki/List_of_U.S._states_by_population",
    "https://en.wikipedia.org/wiki/List_of_cities_in_the_United_States",
    "https://en.wikipedia.org/wiki/List_of_languages_by_number_of_native_speakers",
    "https://en.wikipedia.org/wiki/List_of_countries_by_GDP",
    "https://en.wikipedia.org/wiki/List_of_countries_by_life_expectancy",
    "https://en.wikipedia.org/wiki/List_of_Nobel_laureates",
    "https://en.wikipedia.org/wiki/List_of_Marvel_Cinematic_Universe_films",
    "https://en.wikipedia.org/wiki/List_of_highest-grossing_films",
    "https://en.wikipedia.org/wiki/List_of_plays_by_Shakespeare",
    "https://en.wikipedia.org/wiki/List_of_Harry_Potter_characters",
    "https://en.wikipedia.org/wiki/List_of_countries_and_dependencies_by_area",
    
    # GENERAL KNOWLEDGE HUBS
    "https://en.wikipedia.org/wiki/Outline_of_the_United_States",
    "https://en.wikipedia.org/wiki/Outline_of_science",
    "https://en.wikipedia.org/wiki/Outline_of_technology",
    "https://en.wikipedia.org/wiki/Outline_of_history",
    "https://en.wikipedia.org/wiki/Outline_of_geography",
    "https://en.wikipedia.org/wiki/Outline_of_health_sciences",
    "https://en.wikipedia.org/wiki/Outline_of_mathematics",
    "https://en.wikipedia.org/wiki/Outline_of_philosophy",
    "https://en.wikipedia.org/wiki/Outline_of_culture",
    "https://en.wikipedia.org/wiki/Outline_of_sports",
    "https://en.wikipedia.org/wiki/Outline_of_music",
    
    # NUMBERS/REFERENCE
    "https://en.wikipedia.org/wiki/Numbers",
    "https://en.wikipedia.org/wiki/Integer",
    "https://en.wikipedia.org/wiki/Prime_number",
    "https://en.wikipedia.org/wiki/Decimal",
    "https://en.wikipedia.org/wiki/Hexadecimal",
    "https://en.wikipedia.org/wiki/Binary_number",
    "https://en.wikipedia.org/wiki/Number_theory",
    "https://en.wikipedia.org/wiki/Numerology",
    "https://en.wikipedia.org/wiki/Mathematical_constant",
    "https://en.wikipedia.org/wiki/List_of_mathematical_symbols",
    
    # HISTORY EVENTS & PEOPLE
    "https://en.wikipedia.org/wiki/World_War_II",
    "https://en.wikipedia.org/wiki/World_War_I",
    "https://en.wikipedia.org/wiki/Industrial_Revolution",
    "https://en.wikipedia.org/wiki/Ancient_Egypt",
    "https://en.wikipedia.org/wiki/Roman_Empire",
    "https://en.wikipedia.org/wiki/Medieval_period",
    "https://en.wikipedia.org/wiki/Renaissance",
    "https://en.wikipedia.org/wiki/Enlightenment",
    "https://en.wikipedia.org/wiki/American_Civil_War",
    "https://en.wikipedia.org/wiki/French_Revolution",
    "https://en.wikipedia.org/wiki/Albert_Einstein",
    "https://en.wikipedia.org/wiki/Stephen_Hawking",
    "https://en.wikipedia.org/wiki/Marie_Curie",
    "https://en.wikipedia.org/wiki/Nikola_Tesla",
    "https://en.wikipedia.org/wiki/Steve_Jobs",
    "https://en.wikipedia.org/wiki/Bill_Gates",
    "https://en.wikipedia.org/wiki/Mark_Zuckerberg",
    "https://en.wikipedia.org/wiki/Elon_Musk",
    "https://en.wikipedia.org/wiki/Abraham_Lincoln",
    "https://en.wikipedia.org/wiki/George_Washington",
    
    # ENTERTAINMENT & CULTURE
    "https://en.wikipedia.org/wiki/List_of_Batman_films",
    "https://en.wikipedia.org/wiki/List_of_Superman_films",
    "https://en.wikipedia.org/wiki/Star_Wars",
    "https://en.wikipedia.org/wiki/Marvel_Cinematic_Universe",
    "https://en.wikipedia.org/wiki/Breaking_Bad",
    "https://en.wikipedia.org/wiki/Game_of_Thrones",
    "https://en.wikipedia.org/wiki/The_Office_(American_TV_series)",
    "https://en.wikipedia.org/wiki/Friends_(TV_series)",
    "https://en.wikipedia.org/wiki/The_Beatles",
    "https://en.wikipedia.org/wiki/Pink_Floyd",
    "https://en.wikipedia.org/wiki/The_Rolling_Stones",
    
    # SPORTS & GAMES
    "https://en.wikipedia.org/wiki/FIFA_World_Cup",
    "https://en.wikipedia.org/wiki/Super_Bowl",
    "https://en.wikipedia.org/wiki/Olympics",
    "https://en.wikipedia.org/wiki/Chess",
    "https://en.wikipedia.org/wiki/League_of_Legends",
    "https://en.wikipedia.org/wiki/Fortnite",
    "https://en.wikipedia.org/wiki/Minecraft",
    "https://en.wikipedia.org/wiki/The_Legend_of_Zelda",
    "https://en.wikipedia.org/wiki/Super_Mario",
    "https://en.wikipedia.org/wiki/Call_of_Duty",
    
    # COUNTRIES & GEOGRAPHY
    "https://en.wikipedia.org/wiki/United_States",
    "https://en.wikipedia.org/wiki/United_Kingdom",
    "https://en.wikipedia.org/wiki/France",
    "https://en.wikipedia.org/wiki/Germany",
    "https://en.wikipedia.org/wiki/China",
    "https://en.wikipedia.org/wiki/Japan",
    "https://en.wikipedia.org/wiki/India",
    "https://en.wikipedia.org/wiki/Brazil",
    "https://en.wikipedia.org/wiki/Russia",
    "https://en.wikipedia.org/wiki/Australia",
    "https://en.wikipedia.org/wiki/Canada",
    "https://en.wikipedia.org/wiki/Mexico",
    "https://en.wikipedia.org/wiki/New_York_City",
    "https://en.wikipedia.org/wiki/London",
    "https://en.wikipedia.org/wiki/Paris",
    "https://en.wikipedia.org/wiki/Tokyo",
    "https://en.wikipedia.org/wiki/Dubai",
    "https://en.wikipedia.org/wiki/Sydney",
    
    # DISEASES & MEDICINE
    "https://en.wikipedia.org/wiki/COVID-19",
    "https://en.wikipedia.org/wiki/Cancer",
    "https://en.wikipedia.org/wiki/Heart_disease",
    "https://en.wikipedia.org/wiki/Diabetes",
    "https://en.wikipedia.org/wiki/Alzheimer%27s_disease",
    "https://en.wikipedia.org/wiki/Autism",
    "https://en.wikipedia.org/wiki/Depression_(mental_disorder)",
    "https://en.wikipedia.org/wiki/Obesity",
    "https://en.wikipedia.org/wiki/HIV/AIDS",
    "https://en.wikipedia.org/wiki/Influenza",
    
    # ACADEMIC & RESEARCH
    "https://www.journals.elsevier.com/",
    "https://www.springer.com/",
    "https://www.wiley.com/",
    "https://www.taylorfrancis.com/",
    "https://openreview.net/",
    "https://www.semanticscholar.org/",
    "https://www.researchgate.net/",
    "https://www.academia.edu/",
    "https://www.ncbi.nlm.nih.gov/pubmed/",
    "https://www.tandfonline.com/",
    
    # MORE TECH COMPANIES
    "https://en.wikipedia.org/wiki/Dell_Technologies",
    "https://en.wikipedia.org/wiki/HP_Inc.",
    "https://en.wikipedia.org/wiki/Lenovo",
    "https://en.wikipedia.org/wiki/Samsung",
    "https://en.wikipedia.org/wiki/LG_Electronics",
    "https://en.wikipedia.org/wiki/Sony",
    "https://en.wikipedia.org/wiki/Canon_Inc.",
    "https://en.wikipedia.org/wiki/Nikon",
    "https://en.wikipedia.org/wiki/Panasonic",
    "https://en.wikipedia.org/wiki/Qualcomm",
    "https://en.wikipedia.org/wiki/ARM_Holdings",
    "https://en.wikipedia.org/wiki/AMD",
    "https://en.wikipedia.org/wiki/Broadcom",
    "https://en.wikipedia.org/wiki/Western_Digital",
    "https://en.wikipedia.org/wiki/Seagate_Technology",
    "https://en.wikipedia.org/wiki/Kingston_Technology",
    "https://en.wikipedia.org/wiki/Corsair_Gaming",
    "https://en.wikipedia.org/wiki/ASUS",
    "https://en.wikipedia.org/wiki/Gigabyte_Technology",
    "https://en.wikipedia.org/wiki/MSI_(company)",
    
    # SOCIAL MEDIA & PLATFORMS
    "https://en.wikipedia.org/wiki/YouTube",
    "https://en.wikipedia.org/wiki/Instagram",
    "https://en.wikipedia.org/wiki/TikTok",
    "https://en.wikipedia.org/wiki/Snapchat",
    "https://en.wikipedia.org/wiki/Pinterest",
    "https://en.wikipedia.org/wiki/Telegram_(software)",
    "https://en.wikipedia.org/wiki/Discord_(software)",
    "https://en.wikipedia.org/wiki/Twitch_(streaming_service)",
    "https://en.wikipedia.org/wiki/LinkedIn",
    "https://en.wikipedia.org/wiki/Nextdoor_(website)",
    
    # MORE SCIENCE & NATURE
    "https://en.wikipedia.org/wiki/Physics",
    "https://en.wikipedia.org/wiki/Chemistry",
    "https://en.wikipedia.org/wiki/Biology",
    "https://en.wikipedia.org/wiki/Geology",
    "https://en.wikipedia.org/wiki/Astronomy",
    "https://en.wikipedia.org/wiki/Ecology",
    "https://en.wikipedia.org/wiki/Botany",
    "https://en.wikipedia.org/wiki/Zoology",
    "https://en.wikipedia.org/wiki/Microbiology",
    "https://en.wikipedia.org/wiki/Neuroscience",
    "https://en.wikipedia.org/wiki/Pathology",
    "https://en.wikipedia.org/wiki/Pharmacology",
    "https://en.wikipedia.org/wiki/Immunology",
    "https://en.wikipedia.org/wiki/Genetics",
    "https://en.wikipedia.org/wiki/Psychology",
    
    # MATHEMATICS & LOGIC
    "https://en.wikipedia.org/wiki/Algebra",
    "https://en.wikipedia.org/wiki/Geometry",
    "https://en.wikipedia.org/wiki/Calculus",
    "https://en.wikipedia.org/wiki/Statistics",
    "https://en.wikipedia.org/wiki/Logic",
    "https://en.wikipedia.org/wiki/Set_theory",
    "https://en.wikipedia.org/wiki/Category_theory",
    "https://en.wikipedia.org/wiki/Topology",
    "https://en.wikipedia.org/wiki/Graph_theory",
    "https://en.wikipedia.org/wiki/Discrete_mathematics",
    
    # ENGINEERING & ARCHITECTURE
    "https://en.wikipedia.org/wiki/Software_engineering",
    "https://en.wikipedia.org/wiki/Civil_engineering",
    "https://en.wikipedia.org/wiki/Mechanical_engineering",
    "https://en.wikipedia.org/wiki/Electrical_engineering",
    "https://en.wikipedia.org/wiki/Chemical_engineering",
    "https://en.wikipedia.org/wiki/Aerospace_engineering",
    "https://en.wikipedia.org/wiki/Biomedical_engineering",
    "https://en.wikipedia.org/wiki/Environmental_engineering",
    "https://en.wikipedia.org/wiki/Materials_science",
    "https://en.wikipedia.org/wiki/Nuclear_engineering",
    
    # ART & DESIGN
    "https://en.wikipedia.org/wiki/Art",
    "https://en.wikipedia.org/wiki/Painting",
    "https://en.wikipedia.org/wiki/Sculpture",
    "https://en.wikipedia.org/wiki/Photography",
    "https://en.wikipedia.org/wiki/Graphic_design",
    "https://en.wikipedia.org/wiki/Web_design",
    "https://en.wikipedia.org/wiki/Interior_design",
    "https://en.wikipedia.org/wiki/Fashion_design",
    "https://en.wikipedia.org/wiki/Industrial_design",
    "https://en.wikipedia.org/wiki/Architecture",
    
    # LITERATURE & WRITING
    "https://en.wikipedia.org/wiki/Novel",
    "https://en.wikipedia.org/wiki/Short_story",
    "https://en.wikipedia.org/wiki/Poetry",
    "https://en.wikipedia.org/wiki/Drama",
    "https://en.wikipedia.org/wiki/Essay",
    "https://en.wikipedia.org/wiki/Journalism",
    "https://en.wikipedia.org/wiki/Science_fiction",
    "https://en.wikipedia.org/wiki/Fantasy",
    "https://en.wikipedia.org/wiki/Mystery_fiction",
    "https://en.wikipedia.org/wiki/Romance_novel",
    
    # HISTORY PERIODS
    "https://en.wikipedia.org/wiki/Ancient_history",
    "https://en.wikipedia.org/wiki/Classical_antiquity",
    "https://en.wikipedia.org/wiki/Byzantine_Empire",
    "https://en.wikipedia.org/wiki/Islamic_Golden_Age",
    "https://en.wikipedia.org/wiki/Viking_Age",
    "https://en.wikipedia.org/wiki/Age_of_Exploration",
    "https://en.wikipedia.org/wiki/Age_of_Enlightenment",
    "https://en.wikipedia.org/wiki/Industrial_Age",
    "https://en.wikipedia.org/wiki/Information_Age",
    "https://en.wikipedia.org/wiki/Modern_era",
    
    # FAMOUS STRUCTURES & LANDMARKS
    "https://en.wikipedia.org/wiki/Great_Wall_of_China",
    "https://en.wikipedia.org/wiki/Colosseum",
    "https://en.wikipedia.org/wiki/Statue_of_Liberty",
    "https://en.wikipedia.org/wiki/Eiffel_Tower",
    "https://en.wikipedia.org/wiki/Big_Ben",
    "https://en.wikipedia.org/wiki/Taj_Mahal",
    "https://en.wikipedia.org/wiki/Machu_Picchu",
    "https://en.wikipedia.org/wiki/Christ_the_Redeemer",
    "https://en.wikipedia.org/wiki/Pyramid_of_Giza",
    "https://en.wikipedia.org/wiki/Stonehenge",
    
    # PHILOSOPHY & ETHICS
    "https://en.wikipedia.org/wiki/Metaphysics",
    "https://en.wikipedia.org/wiki/Epistemology",
    "https://en.wikipedia.org/wiki/Ethics",
    "https://en.wikipedia.org/wiki/Aesthetics",
    "https://en.wikipedia.org/wiki/Political_philosophy",
    "https://en.wikipedia.org/wiki/Existentialism",
    "https://en.wikipedia.org/wiki/Stoicism",
    "https://en.wikipedia.org/wiki/Pragmatism",
    "https://en.wikipedia.org/wiki/Rationalism",
    "https://en.wikipedia.org/wiki/Empiricism",
    
    # RELIGIONS & BELIEFS
    "https://en.wikipedia.org/wiki/Christianity",
    "https://en.wikipedia.org/wiki/Islam",
    "https://en.wikipedia.org/wiki/Hinduism",
    "https://en.wikipedia.org/wiki/Buddhism",
    "https://en.wikipedia.org/wiki/Judaism",
    "https://en.wikipedia.org/wiki/Sikhism",
    "https://en.wikipedia.org/wiki/Jainism",
    "https://en.wikipedia.org/wiki/Taoism",
    "https://en.wikipedia.org/wiki/Confucianism",
    "https://en.wikipedia.org/wiki/Atheism",
    
    # FOOD & NUTRITION
    "https://en.wikipedia.org/wiki/Nutrition",
    "https://en.wikipedia.org/wiki/Protein",
    "https://en.wikipedia.org/wiki/Carbohydrate",
    "https://en.wikipedia.org/wiki/Fat",
    "https://en.wikipedia.org/wiki/Vitamin",
    "https://en.wikipedia.org/wiki/Mineral_(nutrient)",
    "https://en.wikipedia.org/wiki/Plant-based_diet",
    "https://en.wikipedia.org/wiki/Vegetarianism",
    "https://en.wikipedia.org/wiki/Veganism",
    "https://en.wikipedia.org/wiki/Cuisine",
    
    # SPORTS & RECREATION
    "https://en.wikipedia.org/wiki/Football",
    "https://en.wikipedia.org/wiki/Basketball",
    "https://en.wikipedia.org/wiki/Tennis",
    "https://en.wikipedia.org/wiki/Golf",
    "https://en.wikipedia.org/wiki/Swimming",
    "https://en.wikipedia.org/wiki/Track_and_field",
    "https://en.wikipedia.org/wiki/Gymnastics",
    "https://en.wikipedia.org/wiki/Martial_arts",
    "https://en.wikipedia.org/wiki/Boxing",
    "https://en.wikipedia.org/wiki/Cycling",
    
    # MOVIES & CINEMA
    "https://en.wikipedia.org/wiki/Film",
    "https://en.wikipedia.org/wiki/Film_genre",
    "https://en.wikipedia.org/wiki/Academy_Awards",
    "https://en.wikipedia.org/wiki/Golden_Globe_Awards",
    "https://en.wikipedia.org/wiki/BAFTA",
    "https://en.wikipedia.org/wiki/Cannes_Film_Festival",
    "https://en.wikipedia.org/wiki/Berlin_International_Film_Festival",
    "https://en.wikipedia.org/wiki/Venice_Film_Festival",
    "https://en.wikipedia.org/wiki/Animation",
    "https://en.wikipedia.org/wiki/Documentary_film",
    
    # MUSIC & PERFORMING ARTS
    "https://en.wikipedia.org/wiki/Music",
    "https://en.wikipedia.org/wiki/Classical_music",
    "https://en.wikipedia.org/wiki/Jazz",
    "https://en.wikipedia.org/wiki/Rock_music",
    "https://en.wikipedia.org/wiki/Pop_music",
    "https://en.wikipedia.org/wiki/Hip_hop_music",
    "https://en.wikipedia.org/wiki/Country_music",
    "https://en.wikipedia.org/wiki/Electronic_music",
    "https://en.wikipedia.org/wiki/Musical_instrument",
    "https://en.wikipedia.org/wiki/Orchestra",
    
    # TELEVISION & STREAMING
    "https://en.wikipedia.org/wiki/Television",
    "https://en.wikipedia.org/wiki/Reality_television",
    "https://en.wikipedia.org/wiki/Game_show",
    "https://en.wikipedia.org/wiki/Sitcom",
    "https://en.wikipedia.org/wiki/Drama_(film_and_television)",
    "https://en.wikipedia.org/wiki/Documentary_television",
    "https://en.wikipedia.org/wiki/Anime",
    "https://en.wikipedia.org/wiki/Manga",
    "https://en.wikipedia.org/wiki/Cartoon",
    "https://en.wikipedia.org/wiki/Comic_book",
    
    # BUSINESS & ECONOMICS
    "https://en.wikipedia.org/wiki/Business",
    "https://en.wikipedia.org/wiki/Economics",
    "https://en.wikipedia.org/wiki/Capitalism",
    "https://en.wikipedia.org/wiki/Socialism",
    "https://en.wikipedia.org/wiki/Communism",
    "https://en.wikipedia.org/wiki/Trade",
    "https://en.wikipedia.org/wiki/Supply_and_demand",
    "https://en.wikipedia.org/wiki/Inflation",
    "https://en.wikipedia.org/wiki/Recession",
    "https://en.wikipedia.org/wiki/Stock_market",
    
    # PSYCHOLOGY & NEUROSCIENCE
    "https://en.wikipedia.org/wiki/Cognitive_psychology",
    "https://en.wikipedia.org/wiki/Social_psychology",
    "https://en.wikipedia.org/wiki/Development_psychology",
    "https://en.wikipedia.org/wiki/Abnormal_psychology",
    "https://en.wikipedia.org/wiki/Personality_psychology",
    "https://en.wikipedia.org/wiki/Memory",
    "https://en.wikipedia.org/wiki/Attention",
    "https://en.wikipedia.org/wiki/Learning",
    "https://en.wikipedia.org/wiki/Emotion",
    "https://en.wikipedia.org/wiki/Consciousness",
    
    # TECHNOLOGY PIONEERS & INNOVATIONS
    "https://en.wikipedia.org/wiki/Alan_Turing",
    "https://en.wikipedia.org/wiki/Grace_Hopper",
    "https://en.wikipedia.org/wiki/Richard_Stallman",
    "https://en.wikipedia.org/wiki/Linus_Torvalds",
    "https://en.wikipedia.org/wiki/Guido_van_Rossum",
    "https://en.wikipedia.org/wiki/Bjarne_Stroustrup",
    "https://en.wikipedia.org/wiki/Dennis_Ritchie",
    "https://en.wikipedia.org/wiki/Niklaus_Wirth",
    "https://en.wikipedia.org/wiki/Donald_Knuth",
    "https://en.wikipedia.org/wiki/Edsger_W._Dijkstra",
    
    # SCIENCE CONCEPTS
    "https://en.wikipedia.org/wiki/Theory_of_relativity",
    "https://en.wikipedia.org/wiki/Quantum_mechanics",
    "https://en.wikipedia.org/wiki/Thermodynamics",
    "https://en.wikipedia.org/wiki/Electromagnetism",
    "https://en.wikipedia.org/wiki/Photon",
    "https://en.wikipedia.org/wiki/Electron",
    "https://en.wikipedia.org/wiki/Atom",
    "https://en.wikipedia.org/wiki/Molecule",
    "https://en.wikipedia.org/wiki/Cell_(biology)",
    "https://en.wikipedia.org/wiki/Evolution",
    
    # MORE REFERENCE & LISTS
    "https://en.wikipedia.org/wiki/List_of_countries_by_name",
    "https://en.wikipedia.org/wiki/List_of_U.S._states",
    "https://en.wikipedia.org/wiki/Periodic_table",
    "https://en.wikipedia.org/wiki/List_of_elements",
    "https://en.wikipedia.org/wiki/List_of_countries_by_HDI",
    "https://en.wikipedia.org/wiki/List_of_natural_resources",
    "https://en.wikipedia.org/wiki/List_of_islands_by_area",
    "https://en.wikipedia.org/wiki/List_of_mountains",
    "https://en.wikipedia.org/wiki/List_of_rivers",
    "https://en.wikipedia.org/wiki/List_of_lakes",
    
    # BIOLOGY TOPICS
    "https://en.wikipedia.org/wiki/Protein_folding",
    "https://en.wikipedia.org/wiki/Photosynthesis",
    "https://en.wikipedia.org/wiki/Metabolism",
    "https://en.wikipedia.org/wiki/Cell_membrane",
    "https://en.wikipedia.org/wiki/Mitochondrion",
    "https://en.wikipedia.org/wiki/Nucleus_(cell)",
    "https://en.wikipedia.org/wiki/Enzyme",
    "https://en.wikipedia.org/wiki/Antibody",
    "https://en.wikipedia.org/wiki/Hormone",
    "https://en.wikipedia.org/wiki/Neuron",
]

DEFAULT_TRACKING_QUERY_PREFIXES = [
    "utm_",
    "mc_",
]

DEFAULT_TRACKING_QUERY_KEYS = [
    "fbclid",
    "gclid",
    "igshid",
    "msclkid",
    "phpsessid",
    "ref",
    "ref_src",
    "session",
    "sessionid",
    "sid",
    "source",
]

DEFAULT_ACTION_PATH_KEYWORDS = [
    "/login",
    "/logout",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/vote",
    "/hide",
    "/reply",
    "/submit",
    "/cart",
    "/checkout",
]

DEFAULT_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap1.xml",
    "/post-sitemap.xml",
    "/page-sitemap.xml",
    "/category-sitemap.xml",
    "/tag-sitemap.xml",
    "/news-sitemap.xml",
    "/video-sitemap.xml",
    "/image-sitemap.xml",
    "/api/sitemap.xml",
    "/sitemap.txt",
    "/sitemap",
    "/site-map",
]


def load_config(config_path=None):
    config = configparser.ConfigParser()
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_path = os.path.join(root_dir, "config.txt")
    config.read(config_path or default_path)
    return config


class CrawlerService:
    def __init__(
        self,
        config=None,
        runtime_options=None,
        log_callback=None,
        status_callback=None,
        save_callback=None,
        stop_event=None,
    ):
        self.config = config or load_config()
        self.runtime_options = runtime_options or {}
        self.log_callback = log_callback or print
        self.status_callback = status_callback
        self.save_callback = save_callback
        self.stop_event = stop_event or threading.Event()

        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.root_dir, "data")
        self.idx_path = os.path.join(self.data_dir, "inverted_index.json")
        self.doc_path = os.path.join(self.data_dir, "doc_info.json")
        self.state_path = os.path.join(self.data_dir, "crawl_state.json")
        os.makedirs(self.data_dir, exist_ok=True)

        self.crawler_name = self.config.get("Crawler", "crawler_name", fallback="SircoAuroraBot")
        self.crawl_limit = self._resolve_int("Crawler", "crawl_limit", 0)
        self.num_workers = max(1, self._resolve_int("Crawler", "num_workers", 20))
        self.min_delay = self._resolve_float("Crawler", "min_delay", 2.0)
        self.max_delay = self._resolve_float("Crawler", "max_delay", 5.0)
        self.request_timeout = max(1, self._resolve_int("Crawler", "request_timeout", 10))
        self.proxy_timeout = max(1, self.config.getint("Proxy", "proxy_timeout", fallback=self.request_timeout))
        self.max_total_size_bytes = max(0, self.config.getint("Data", "max_total_size_mb", fallback=0)) * 1024 * 1024
        self.max_snapshot_file_bytes = max(0, self.config.getint("Data", "max_file_size", fallback=0)) * 1024 * 1024
        self.save_every = max(1, self.runtime_options.get("save_every", 30))
        self.continuous_mode = bool(self.runtime_options.get("continuous", True))
        self.idle_reseed_delay = max(5, int(self.runtime_options.get("idle_reseed_delay", 20)))
        self.rotate_proxy = self.runtime_options.get(
            "rotate_proxy",
            self.config.getboolean("Proxy", "rotate_proxy", fallback=True),
        )
        self.proxies = self._load_proxies()
        self.proxy_index = 0
        
        # NEW: Session for connection pooling + circuit breaker for failed domains
        self.session = requests.Session()
        self.session.headers.update(self.request_headers())
        self.domain_failure_tracker = {}  # Tracks consecutive failures per domain
        self.domain_circuit_breaker = {}  # Temporarily blocks consistently failing domains
        
        self.tracking_query_prefixes = tuple(
            value.lower() for value in self._resolve_list("Crawler", "tracking_query_prefixes", DEFAULT_TRACKING_QUERY_PREFIXES)
        )
        self.tracking_query_keys = {
            value.lower() for value in self._resolve_list("Crawler", "tracking_query_keys", DEFAULT_TRACKING_QUERY_KEYS)
        }
        self.action_path_keywords = tuple(
            value.lower() for value in self._resolve_list("Crawler", "action_path_keywords", DEFAULT_ACTION_PATH_KEYWORDS)
        )
        self.sitemap_candidate_paths = self._resolve_list("Crawler", "sitemap_candidate_paths", DEFAULT_SITEMAP_PATHS)

        seed_urls = self.runtime_options.get("seed_urls")
        self.starting_urls = seed_urls or self._load_seed_urls()

        # DEPTH & BREADTH CONTROLS (for better crawling)
        self.max_pages_per_domain = max(1, self._resolve_int("Crawler", "max_pages_per_domain", 200))
        self.max_crawl_depth = max(0, self._resolve_int("Crawler", "max_crawl_depth", 3))
        self.min_depth_per_domain = max(0, self._resolve_int("Crawler", "min_depth_per_domain", 1))
        self.max_url_path_depth = max(0, self._resolve_int("Crawler", "max_url_path_depth", 8))
        self.max_query_strings = max(1, self._resolve_int("Crawler", "max_query_strings", 5))
        self.query_string_dedup = self.config.getboolean("Crawler", "query_string_dedup", fallback=True)
        self.whitelisted_path_keywords = set(
            kw.lower().strip() for kw in self._resolve_list("Crawler", "whitelisted_path_keywords", []) if kw.strip()
        )
        self.blacklist_patterns = [
            re.compile(pattern.strip()) for pattern in self._resolve_list("Crawler", "blacklist_patterns", []) if pattern.strip()
        ]

        self.queue = PriorityQueue()
        self.lock = threading.Lock()
        self.save_lock = threading.Lock()
        self.visited_urls = set()
        self.known_urls = set()
        self.domain_page_count = {}  # Track pages per domain for diversity
        self.url_depth_map = {}  # Track depth of each URL
        self.url_seed_map = {}  # Track which URLs are seeds (True/False)
        self.seed_urls_crawled = 0  # Count seed URLs processed
        self.seed_urls_remaining = 0  # Count seed URLs still in queue
        self.discovery_phase_active = True  # Track crawl phase
        self.index = {}
        self.webpage_info = {}
        self.doc_words = {}
        self.url_to_doc_id = {}
        self.content_fingerprints = {}
        self.pagerank_graph = {}
        self.robots_parsers = {}
        self.domain_sitemap_discovered = set()
        self.processed_sitemaps = set()
        self.bad_sitemaps = set()
        self.domain_metadata_inflight = set()
        self.sitemap_fetch_inflight = set()
        self.domain_next_request_at = {}
        self.domain_crawl_delay = {}
        self.domain_failure_counts = {}
        self.doc_id_counter = 0
        self.crawl_count = 0
        self.last_saved_count = 0
        self.last_saved_at = None
        self.last_idle_refill = 0.0
        self.resumed_from_state = False
        self.previous_seed_urls = set()  # Track seed URLs from last saved state

    def sleep_with_stop(self, duration, interval=0.2):
        deadline = time.time() + max(0, duration)
        while not self.stop_event.is_set():
            remaining = deadline - time.time()
            if remaining <= 0:
                return True
            time.sleep(min(interval, remaining))
        return False

    def _resolve_int(self, section, option, fallback):
        if option in self.runtime_options:
            return int(self.runtime_options[option])
        return self.config.getint(section, option, fallback=fallback)

    def _resolve_float(self, section, option, fallback):
        if option in self.runtime_options:
            return float(self.runtime_options[option])
        return self.config.getfloat(section, option, fallback=fallback)

    def _resolve_list(self, section, option, fallback):
        raw_value = self.config.get(section, option, fallback="")
        if not raw_value.strip():
            return list(fallback)

        values = []
        for item in raw_value.replace("|", "\n").replace(",", "\n").splitlines():
            cleaned = item.strip()
            if cleaned:
                values.append(cleaned)
        return values or list(fallback)

    def _load_seed_urls(self):
        raw = self.config.get("Crawler", "seed_urls", fallback="")
        if not raw.strip():
            return list(DEFAULT_STARTING_URLS)

        urls = []
        for item in raw.replace(",", "\n").replace("|", "\n").splitlines():
            url = item.strip()
            if url:
                urls.append(url)
        return urls or list(DEFAULT_STARTING_URLS)

    def _load_proxies(self):
        proxy_list = self.runtime_options.get("proxy_list")
        use_proxy = self.runtime_options.get("use_proxy")

        if use_proxy is None:
            use_proxy = self.config.getboolean("Proxy", "use_proxy", fallback=False)

        # Check if VPN SOCKS5 proxy is available
        vpn_proxy = os.environ.get("AURORA_VPN_PROXY")
        if vpn_proxy:
            self.log(f"✓ Using VPN SOCKS5 proxy: {vpn_proxy}")
            return [vpn_proxy]

        if not use_proxy:
            return []

        if proxy_list is None:
            proxy_list = self.config.get("Proxy", "proxy_list", fallback="")

        proxies = [proxy.strip() for proxy in str(proxy_list).split("|") if proxy.strip()]
        if proxies:
            self.log(f"Loaded {len(proxies)} proxies for crawler rotation.")
        return proxies

    def log(self, message):
        self.log_callback(message)

    def publish_status(self, state, message, extra=None):
        if not self.status_callback:
            return

        payload = {
            "state": state,
            "message": message,
            "crawl_count": self.crawl_count,
            "docs_indexed": len(self.webpage_info),
            "words_indexed": len(self.index),
            "queue_size": self.queue.qsize(),
            "last_saved_count": self.last_saved_count,
            "last_saved_at": self.last_saved_at,
            "continuous_mode": self.continuous_mode,
            "save_every": self.save_every,
            "resumed_from_state": self.resumed_from_state,
        }
        if extra:
            payload.update(extra)
        self.status_callback(payload)

    def load_snapshot_files(self):
        if os.path.exists(self.idx_path):
            try:
                with open(self.idx_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.index = {word: set(doc_ids) for word, doc_ids in payload.items()}
            except (OSError, json.JSONDecodeError):
                self.index = {}

        if os.path.exists(self.doc_path):
            try:
                with open(self.doc_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                for doc_id_text, info in payload.items():
                    doc_id = int(doc_id_text)
                    self.webpage_info[doc_id] = {
                        "url": info["url"],
                        "title": info["title"],
                        "description": info["description"],
                        "pagerank": float(info.get("pagerank", 0)),
                    }
                    self.url_to_doc_id[info["url"]] = doc_id
                if self.webpage_info:
                    self.doc_id_counter = max(self.webpage_info) + 1
            except (OSError, json.JSONDecodeError, ValueError, KeyError):
                self.webpage_info = {}
                self.url_to_doc_id = {}

    def load_resume_state(self):
        self.load_snapshot_files()
        if not os.path.exists(self.state_path):
            return False

        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return False

        queue_items = [url for url in state.get("queue", []) if isinstance(url, str) and url]
        with self.lock:
            self.visited_urls = {url for url in (self.normalize_url(item) for item in state.get("visited_urls", [])) if url}
            self.known_urls = {url for url in (self.normalize_url(item) for item in state.get("known_urls", [])) if url}
            self.pagerank_graph = {
                self.normalize_url(url): {normalized for normalized in (self.normalize_url(link) for link in links) if normalized}
                for url, links in state.get("pagerank_graph", {}).items()
                if self.normalize_url(url)
            }
            self.domain_sitemap_discovered = {origin for origin in state.get("domain_sitemap_discovered", []) if origin}
            self.processed_sitemaps = {url for url in (self.normalize_url(item) for item in state.get("processed_sitemaps", [])) if url}
            self.bad_sitemaps = {url for url in (self.normalize_url(item) for item in state.get("bad_sitemaps", [])) if url}
            self.doc_words = {
                int(doc_id): set(words)
                for doc_id, words in state.get("doc_words", {}).items()
            }
            self.content_fingerprints = {
                fingerprint: int(doc_id)
                for fingerprint, doc_id in state.get("content_fingerprints", {}).items()
            }
            self.url_to_doc_id.update(
                {
                    normalized_url: int(doc_id)
                    for url, doc_id in state.get("url_to_doc_id", {}).items()
                    if (normalized_url := self.normalize_url(url))
                }
            )
            self.doc_id_counter = max(
                int(state.get("doc_id_counter", 0)),
                self.doc_id_counter,
            )
            self.crawl_count = int(state.get("crawl_count", self.crawl_count))
            self.last_saved_count = int(state.get("last_saved_count", self.last_saved_count))
            self.last_saved_at = state.get("last_saved_at")
            
            # NEW: Load priority crawling metadata
            saved_url_depth_map = state.get("url_depth_map", {})
            saved_url_seed_map = state.get("url_seed_map", {})
            self.seed_urls_crawled = int(state.get("seed_urls_crawled", 0))
            
            # Restore depth and seed mappings
            for url, depth in saved_url_depth_map.items():
                normalized = self.normalize_url(url)
                if normalized:
                    self.url_depth_map[normalized] = depth
            
            for url, is_seed in saved_url_seed_map.items():
                normalized = self.normalize_url(url)
                if normalized:
                    self.url_seed_map[normalized] = is_seed
            
            # NEW: Load previous seed URLs to detect new ones
            self.previous_seed_urls = set(state.get("seed_urls", []))

            for url in self.starting_urls:
                normalized = self.normalize_url(url)
                if normalized:
                    self.known_urls.add(normalized)

            # Restore queue with priority information
            for url in queue_items:
                normalized = self.normalize_url(url)
                if normalized:
                    is_seed = self.url_seed_map.get(normalized, False)
                    depth = self.url_depth_map.get(normalized, 0)
                    # Re-enqueue with correct priority
                    priority = (0 if is_seed else 1, depth, normalized)
                    self.queue.put((priority, normalized))
                    if is_seed:
                        self.seed_urls_remaining += 1

        self.resumed_from_state = bool(queue_items or self.visited_urls or self.webpage_info)
        return self.resumed_from_state

    def check_for_new_seeds(self):
        """
        Detect newly added seed URLs and enqueue them with high priority.
        Called when resuming from a saved state.
        
        New seeds are queued with is_seed=True so they get:
        - Priority 0 (highest)
        - Depth limit of 20 (vs 3 for discovered URLs)
        - Deep crawling to populate index with key topics
        """
        current_seeds = set(self.starting_urls)
        new_seeds = current_seeds - self.previous_seed_urls
        removed_seeds = self.previous_seed_urls - current_seeds
        
        if new_seeds:
            self.log("")
            self.log(f"🔍 DETECTED {len(new_seeds)} NEW SEED URL(S):")
            for url in sorted(new_seeds):
                self.log(f"   ➕ {url}")
            self.log(f"⏳ Enqueueing new seeds with HIGH PRIORITY (depth 0-20)...")
            
            enqueued = 0
            for url in sorted(new_seeds):  # Sort for determinism
                if self.enqueue_url(url, is_seed=True, depth=0):
                    enqueued += 1
            
            self.log(f"✓ Enqueued {enqueued}/{len(new_seeds)} new seed URLs for intelligent deep crawling")
            if enqueued > 0:
                self.log(f"   Seeds will be crawled deeply (20 levels) while maintaining resume capability")
        
        if removed_seeds:
            self.log(f"📝 Note: {len(removed_seeds)} seed URL(s) were removed from config")
            for url in sorted(removed_seeds):
                self.log(f"   ➖ {url}")

    def save_state(self):
        with self.lock:
            with self.queue.mutex:
                # PriorityQueue stores tuples: (priority, url)
                # Extract just the URLs for storage
                queue_snapshot = [url for (priority, url) in self.queue.queue]

            state = {
                "queue": queue_snapshot,
                "visited_urls": sorted(self.visited_urls),
                "known_urls": sorted(self.known_urls),
                "pagerank_graph": {
                    url: sorted(links)
                    for url, links in self.pagerank_graph.items()
                },
                "domain_sitemap_discovered": sorted(self.domain_sitemap_discovered),
                "processed_sitemaps": sorted(self.processed_sitemaps),
                "bad_sitemaps": sorted(self.bad_sitemaps),
                "doc_words": {
                    str(doc_id): sorted(words)
                    for doc_id, words in self.doc_words.items()
                },
                "content_fingerprints": dict(self.content_fingerprints),
                "url_to_doc_id": {
                    url: doc_id
                    for url, doc_id in self.url_to_doc_id.items()
                },
                "doc_id_counter": self.doc_id_counter,
                "crawl_count": self.crawl_count,
                "last_saved_count": self.last_saved_count,
                "last_saved_at": self.last_saved_at,
                # NEW: Store seed URLs to detect new ones later
                "seed_urls": sorted(self.starting_urls),
                # NEW: Store depth and seed status for priority crawling
                "url_depth_map": dict(self.url_depth_map),
                "url_seed_map": dict(self.url_seed_map),
                "seed_urls_crawled": self.seed_urls_crawled,
            }

        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)

    def seed_queue(self):
        """
        Initialize the crawler queue with starting seed URLs.
        Seeds are enqueued with is_seed=True for priority handling.
        """
        seeded = 0
        for url in self.starting_urls:
            if self.enqueue_url(url, is_seed=True, depth=0):
                seeded += 1
        self.log(f"✓ Seeded crawler queue with {seeded} starting URLs.")
        self.log(f"   Seeds will crawl deeply (max depth 20) to build knowledge base")

    def normalize_url(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if scheme == "http" and netloc.endswith(":80"):
            netloc = netloc[:-3]
        if scheme == "https" and netloc.endswith(":443"):
            netloc = netloc[:-4]

        normalized_path = parsed.path or "/"
        if normalized_path != "/" and normalized_path.endswith("/"):
            normalized_path = normalized_path.rstrip("/")

        filtered_query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lowered_key = key.lower()
            if lowered_key in self.tracking_query_keys:
                continue
            if any(lowered_key.startswith(prefix) for prefix in self.tracking_query_prefixes):
                continue
            filtered_query.append((key, value))

        normalized = (
            scheme,
            netloc,
            normalized_path,
            parsed.params,
            urlencode(sorted(filtered_query)),
            "",
        )
        return urlunparse(normalized)

    def get_origin(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"

    def enqueue_url(self, url, is_seed=False, depth=None):
        """
        Enqueue URL with priority-based system.
        Seeds get priority 0, discovered URLs get priority 1.
        Depth defaults: seeds=20, discovered=3
        
        IMPORTANT: Seeds at depth 0 bypass known_urls check to allow re-enqueueing
        from state reload. This is intentional - seeds must always be crawlable.
        """
        normalized = self.normalize_url(url)
        if not normalized:
            return False
        if self.should_skip_url(normalized):
            return False
        
        # Determine depth limit based on seed status
        if depth is None:
            depth = 0
        
        max_allowed_depth = 20 if is_seed else self.max_crawl_depth
        if depth > max_allowed_depth:
            return False
        
        # Don't apply domain limits to seeds - they're important!
        # Only check domain limits for discovered URLs
        if not is_seed and not self.can_crawl_from_domain(normalized):
            return False

        with self.lock:
            # FIXED: Allow seeds at depth 0 to bypass known_urls check
            # This lets seeds be re-enqueued when resuming from saved state
            # But prevent re-enqueueing the same discovered URL twice
            if normalized in self.visited_urls:
                # Already crawled - don't re-crawl
                return False
            
            # For discovered URLs, prevent duplicate enqueueing to save queue space
            # For seeds, allow re-enqueueing at depth 0 (fresh seed detection)
            if normalized in self.known_urls and not (is_seed and depth == 0):
                return False
            
            self.known_urls.add(normalized)
            self.url_depth_map[normalized] = depth
            self.url_seed_map[normalized] = is_seed
            
            # Priority: seeds get 0 (highest), discovered get 1
            # Within same priority, prefer shallower URLs
            priority = (0 if is_seed else 1, depth, normalized)
            self.queue.put((priority, normalized))
            
            if is_seed:
                self.seed_urls_remaining += 1
        
        return True
    
    def requeue_url(self, url, is_seed=False):
        """Requeue a URL that failed (retry)."""
        normalized = self.normalize_url(url)
        if not normalized:
            return False
        if self.should_skip_url(normalized):
            return False
        
        # Check domain page limits for URL diversity
        if not self.can_crawl_from_domain(normalized):
            return False
        
        current_depth = self.url_depth_map.get(normalized, 0)
        max_allowed_depth = 20 if is_seed else self.max_crawl_depth
        
        if current_depth > max_allowed_depth:
            return False

        with self.lock:
            # Only requeue if not already visited
            if normalized in self.visited_urls:
                return False
            
            # Re-add to known URLs if it was cleared
            self.known_urls.add(normalized)
            
            priority = (0 if is_seed else 1, current_depth, normalized)
            self.queue.put((priority, normalized))
        
        return True

    def get_next_proxy(self):
        if not self.proxies:
            return None

        if self.rotate_proxy:
            proxy_url = self.proxies[self.proxy_index % len(self.proxies)]
            self.proxy_index += 1
        else:
            proxy_url = self.proxies[0]

        return {"http": proxy_url, "https": proxy_url}

    def request_headers(self):
        """Generate realistic request headers that look like a browser, not a bot."""
        # Rotate through common browser User-Agents to avoid detection
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0",
        ]
        # Pick a random bot identity but rotate based on URL to be consistent per domain
        ua_index = hash(self.crawler_name) % len(user_agents)
        user_agent = user_agents[ua_index]
        
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def get_domain_delay(self, origin):
        crawl_delay = self.domain_crawl_delay.get(origin)
        if crawl_delay is not None:
            return max(float(crawl_delay), self.min_delay)
        return random.uniform(self.min_delay, self.max_delay)

    def wait_for_domain_slot(self, origin):
        while not self.stop_event.is_set():
            with self.lock:
                next_allowed = self.domain_next_request_at.get(origin, 0.0)
            remaining = next_allowed - time.time()
            if remaining <= 0:
                return True
            if not self.sleep_with_stop(min(remaining, 0.5)):
                return False
        return False

    def record_domain_request(self, origin, success):
        with self.lock:
            if success:
                self.domain_failure_counts[origin] = 0
                delay = self.get_domain_delay(origin)
            else:
                failures = self.domain_failure_counts.get(origin, 0) + 1
                self.domain_failure_counts[origin] = failures
                delay = min(30.0, self.get_domain_delay(origin) + failures * 2.0)
            self.domain_next_request_at[origin] = time.time() + delay

    def request_url(self, url, proxies=None, timeout=None):
        """
        Fetch URL with intelligent retry logic, timeouts, and circuit breaker.
        
        Features:
        - Exponential backoff retries (1s, 2s, 4s)
        - Adaptive timeouts (8s default, 12s max)
        - Circuit breaker for consistently failing domains
        - Connection reuse via session
        """
        origin = self.get_origin(url)
        
        # Check circuit breaker: skip if domain is temporarily blocked
        if origin and self.domain_circuit_breaker.get(origin):
            circuit_info = self.domain_circuit_breaker[origin]
            if time.time() < circuit_info['until']:
                raise requests.RequestException(
                    f"Skipping {origin}: Circuit breaker active (failed {circuit_info['failures']} times)"
                )
            else:
                # Circuit breaker expired, reset
                del self.domain_circuit_breaker[origin]
                if origin in self.domain_failure_tracker:
                    del self.domain_failure_tracker[origin]
        
        if origin and not self.wait_for_domain_slot(origin):
            raise requests.RequestException("crawler stop requested while waiting for domain delay")

        # Determine timeout: shorter than default for faster failure detection
        if timeout is None:
            timeout = 8 if not proxies else 10  # Reduced from 10 and 15
        
        # FIXED: Much shorter retry delays - 0.1s, 0.2s, 0.3s instead of 1s, 2s, 4s
        # This allows workers to respond to stop_event quickly even during retries
        max_retries = 3
        retry_delays = [0.1, 0.2, 0.3]  # MUCH shorter to allow instant stop
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(
                    url,
                    timeout=timeout,
                    proxies=proxies,
                    headers=self.request_headers(),  # Send headers with each request
                    verify=False,  # SSL verification disabled for public crawling
                    allow_redirects=True,
                )
                
                # Handle rate limiting and blocking (403, 429)
                if response.status_code == 429:  # Too Many Requests
                    # Rate limited - back off and try later
                    if attempt < max_retries - 1:
                        if self.stop_event.is_set():
                            raise requests.RequestException("Crawler stop requested")
                        # Exponential backoff for rate limiting
                        wait_time = retry_delays[attempt] * 2
                        if not self.sleep_with_stop(wait_time, interval=0.05):
                            raise requests.RequestException("Crawler stop requested during retry backoff")
                        continue
                    else:
                        # Give up after retries
                        if origin:
                            self.log(f"   ⚠ Rate limited (429) by {origin}, blocking for 15 min")
                            self.domain_circuit_breaker[origin] = {
                                'until': time.time() + 900,
                                'failures': 0,
                            }
                        raise requests.RequestException(f"Rate limited by {origin}")
                
                elif response.status_code == 403:  # Forbidden
                    # Active blocking - might want to back off
                    if origin:
                        self.log(f"   ⊘ Forbidden (403) by {origin} (likely bot detection)")
                        # Hard block for longer period
                        self.domain_circuit_breaker[origin] = {
                            'until': time.time() + 1800,  # 30 minutes
                            'failures': 0,
                        }
                    raise requests.RequestException(f"Blocked (403) by {origin}")
                
                # Success: reset failure counters
                if origin:
                    if origin in self.domain_failure_tracker:
                        del self.domain_failure_tracker[origin]
                    # Only count 2xx/3xx as success
                    self.record_domain_request(origin, success=response.status_code < 400)
                
                return response
                
            except requests.Timeout as e:
                # Timeout - retry with TINY backoff (allows instant stop)
                last_exception = e
                if attempt < max_retries - 1:
                    if self.stop_event.is_set():
                        raise requests.RequestException("Crawler stop requested during retry backoff")
                    wait_time = retry_delays[attempt]
                    # Use sleep_with_stop so we check stop_event every 0.05s
                    if not self.sleep_with_stop(wait_time, interval=0.05):
                        raise requests.RequestException("Crawler stop requested during retry backoff")
                else:
                    # Final timeout after retries - log domain failure
                    if origin:
                        failures = self.domain_failure_tracker.get(origin, 0) + 1
                        self.domain_failure_tracker[origin] = failures
                        self.record_domain_request(origin, success=False)
                        
                        # Activate circuit breaker after 5 consecutive failures
                        if failures >= 5:
                            self.domain_circuit_breaker[origin] = {
                                'until': time.time() + 600,  # Block for 10 minutes
                                'failures': failures,
                            }
                            self.log(f"   ⚠ Circuit breaker: {origin} blocked (5+ timeouts)")
            
            except (requests.ConnectionError, requests.RequestException) as e:
                # Connection error - likely domain is down or unreachable
                last_exception = e
                if origin:
                    failures = self.domain_failure_tracker.get(origin, 0) + 1
                    self.domain_failure_tracker[origin] = failures
                    self.record_domain_request(origin, success=False)
                    
                    # Faster circuit breaker for connection errors (domain unreachable)
                    if failures >= 3:
                        self.domain_circuit_breaker[origin] = {
                            'until': time.time() + 900,  # Block for 15 minutes
                            'failures': failures,
                        }
                        self.log(f"   ⚠ Circuit breaker: {origin} blocked (unreachable)")
                
                # FIXED: Don't retry on connection errors - fail immediately
                # Connection refused/unreachable won't get better with retries
                # Only retry on timeouts which might be transient
                raise last_exception
        
        # All retries exhausted
        if last_exception:
            raise last_exception
        else:
            raise requests.RequestException(f"Failed to fetch {url} after {max_retries} attempts")

    def should_skip_url(self, url):
        """Check if a URL should be skipped based on various filters."""
        parsed = urlparse(url)
        origin = parsed.netloc
        lowered_path = parsed.path.lower()
        
        # ACTION PATH KEYWORDS: Skip login, cart, etc.
        if any(keyword in lowered_path for keyword in self.action_path_keywords):
            return True

        # QUERY STRING DEDUP: Normalize URLs by removing/ignoring query strings
        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        if len(query_items) > self.max_query_strings:
            return True
        
        # PATH DEPTH LIMIT: Don't crawl URLs that are too deep
        if self.max_url_path_depth > 0:
            path_depth = len([p for p in parsed.path.split('/') if p])
            if path_depth > self.max_url_path_depth:
                return True
        
        # WHITELIST CHECK: If whitelist exists, only crawl matching paths
        if self.whitelisted_path_keywords:
            if not any(keyword in lowered_path for keyword in self.whitelisted_path_keywords):
                return True
        
        # BLACKLIST CHECK: Skip matching patterns
        if self.blacklist_patterns:
            if any(pattern.search(url) for pattern in self.blacklist_patterns):
                return True

        return False
    
    def can_crawl_from_domain(self, url):
        """Check if we can crawl this URL based on domain page limits and depth constraints."""
        parsed = urlparse(url)
        origin = parsed.netloc
        
        with self.lock:
            current_count = self.domain_page_count.get(origin, 0)
        
        # Max pages per domain check
        if current_count >= self.max_pages_per_domain:
            return False
        
        return True
    
    def record_domain_crawl(self, url):
        """Record that we're crawling a URL from a domain."""
        parsed = urlparse(url)
        origin = parsed.netloc
        
        with self.lock:
            self.domain_page_count[origin] = self.domain_page_count.get(origin, 0) + 1

    def should_stop(self):
        return self.stop_event.is_set() or (self.crawl_limit > 0 and self.crawl_count >= self.crawl_limit)

    def sitemap_candidate_urls(self, origin):
        return [f"{origin}{path}" for path in self.sitemap_candidate_paths]

    def managed_data_paths(self):
        return [self.idx_path, self.doc_path, self.state_path]

    def build_snapshot_payloads(self, index_snapshot, doc_snapshot, graph_snapshot, crawl_count):
        pagerank_scores = compute_pagerank(graph_snapshot) if graph_snapshot else {}

        # Collect all content fingerprints for duplicate detection
        duplicate_fingerprints = set(self.content_fingerprints.keys()) if self.content_fingerprints else set()

        doc_data = {}
        for doc_id, info in doc_snapshot.items():
            url = info["url"]
            
            # Calculate Panda score (content quality) - NOW WITH PROPER CONTENT
            panda_score_result = score_content_quality(
                content_text=info.get("content", ""),  # FIXED: Use actual content, not stemmed words
                html_text="",  # We don't store original HTML, using empty
                title=info.get("title", ""),
                word_count=info.get("word_count", len(info.get("words", []))),  # FIXED: Use actual word count
                keywords=None,
                duplicate_fingerprints=duplicate_fingerprints,
                content_fingerprint=info.get("content_fingerprint"),
                days_old=None,  # No timestamp tracking yet
            )
            panda_score = panda_score_result.get("overall_score", 0.5)
            
            # Calculate Penguin score (link quality)
            inbound_links = [
                u for u, targets in graph_snapshot.items()
                if url in targets
            ] if graph_snapshot else []
            outbound_links = graph_snapshot.get(url, []) if graph_snapshot else []
            
            penguin_score_result = score_link_quality(
                target_url=url,
                backlinks_data=[{
                    'domain': urlparse(link).netloc or 'unknown',
                    'anchor_text': f"link from {urlparse(link).netloc}",
                }  for link in inbound_links],
                inbound_link_count=len(inbound_links),
                outbound_link_count=len(outbound_links),
            )
            penguin_score = penguin_score_result.get("overall_score", 0.5)
            
            doc_data[str(doc_id)] = {
                "url": url,
                "title": info["title"],
                "description": info["description"],
                "content": info.get("content", ""),  # NEW: Store content for search relevance
                "pagerank": pagerank_scores.get(url, 0),
                "panda_score": round(panda_score, 4),
                "penguin_score": round(penguin_score, 4),
            }

        with self.lock:
            with self.queue.mutex:
                queue_snapshot = list(self.queue.queue)

            state_data = {
                "queue": queue_snapshot,
                "visited_urls": sorted(self.visited_urls),
                "known_urls": sorted(self.known_urls),
                "pagerank_graph": {
                    url: sorted(links)
                    for url, links in self.pagerank_graph.items()
                },
                "domain_sitemap_discovered": sorted(self.domain_sitemap_discovered),
                "processed_sitemaps": sorted(self.processed_sitemaps),
                "bad_sitemaps": sorted(self.bad_sitemaps),
                "doc_words": {
                    str(doc_id): sorted(words)
                    for doc_id, words in self.doc_words.items()
                },
                "content_fingerprints": dict(self.content_fingerprints),
                "url_to_doc_id": {
                    url: doc_id
                    for url, doc_id in self.url_to_doc_id.items()
                },
                "doc_id_counter": self.doc_id_counter,
                "crawl_count": crawl_count,
                "last_saved_count": self.last_saved_count,
                "last_saved_at": self.last_saved_at,
            }

        idx_json = json.dumps(index_snapshot, indent=2, sort_keys=True)
        doc_json = json.dumps(doc_data, indent=2, sort_keys=True)
        state_json = json.dumps(state_data, indent=2, sort_keys=True)
        return idx_json, doc_json, state_json, len(doc_data), len(index_snapshot)

    def enforce_data_limits(self, idx_json, doc_json, state_json):
        file_sizes = {
            self.idx_path: len(idx_json.encode("utf-8")),
            self.doc_path: len(doc_json.encode("utf-8")),
            self.state_path: len(state_json.encode("utf-8")),
        }

        if self.max_snapshot_file_bytes > 0:
            for path, size in file_sizes.items():
                if size > self.max_snapshot_file_bytes:
                    return False, f"{os.path.basename(path)} would exceed the configured max file size"

        if self.max_total_size_bytes > 0:
            projected_total = sum(file_sizes.values())
            if projected_total > self.max_total_size_bytes:
                return False, "projected crawl data would exceed the configured total data limit"

        return True, None

    def parse_robots(self, origin, text):
        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        parser.parse(text.splitlines())
        self.robots_parsers[origin] = parser
        try:
            crawl_delay = parser.crawl_delay("*")
        except Exception:
            crawl_delay = None
        if crawl_delay is not None:
            self.domain_crawl_delay[origin] = max(float(crawl_delay), self.min_delay)

        sitemap_urls = []
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip().lower() == "sitemap":
                sitemap_url = self.normalize_url(value.strip())
                if sitemap_url:
                    sitemap_urls.append(sitemap_url)
        return sitemap_urls

    def can_fetch(self, url):
        origin = self.get_origin(url)
        parser = self.robots_parsers.get(origin)
        if not parser:
            return True
        try:
            return parser.can_fetch(self.crawler_name, url)
        except Exception:
            return True

    def discover_domain_metadata(self, current_url, proxies):
        origin = self.get_origin(current_url)
        if not origin:
            return

        with self.lock:
            if origin in self.domain_sitemap_discovered:
                return
            if origin in self.domain_metadata_inflight:
                return
            self.domain_metadata_inflight.add(origin)

        try:
            sitemap_urls = []
            robots_url = f"{origin}/robots.txt"
            try:
                response = self.request_url(robots_url, proxies=proxies, timeout=min(self.request_timeout, 10))
                if response.status_code < 400:
                    sitemap_urls.extend(self.parse_robots(origin, response.text))
                    self.log(f"   Robots discovered for {origin}")
            except requests.RequestException:
                pass

            for sitemap_url in self.sitemap_candidate_urls(origin):
                sitemap_urls.append(sitemap_url)

            seen = set()
            for sitemap_url in sitemap_urls:
                if sitemap_url in seen:
                    continue
                seen.add(sitemap_url)
                self.process_sitemap(sitemap_url, proxies)
        finally:
            with self.lock:
                self.domain_metadata_inflight.discard(origin)
                self.domain_sitemap_discovered.add(origin)

    def decode_sitemap_payload(self, sitemap_url, response):
        content = response.content
        content_encoding = response.headers.get("content-encoding", "").lower()
        if normalized_sitemap := self.normalize_url(sitemap_url):
            sitemap_url = normalized_sitemap

        if sitemap_url.endswith(".gz") or "gzip" in content_encoding:
            try:
                content = gzip.decompress(content)
            except OSError:
                return None, None

        try:
            text = content.decode(response.encoding or "utf-8", errors="ignore")
        except (LookupError, AttributeError):
            text = content.decode("utf-8", errors="ignore")

        return content, text

    def parse_sitemap_xml(self, sitemap_url, content, proxies):
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return False

        tag = root.tag.split("}")[-1].lower()
        discovered = 0

        if tag == "sitemapindex":
            for element in root.findall(".//{*}loc"):
                child_url = self.normalize_url((element.text or "").strip())
                if child_url:
                    self.process_sitemap(child_url, proxies)
                    discovered += 1
            if discovered:
                self.log(f"   Sitemap index {sitemap_url} yielded {discovered} child sitemaps.")
            return True

        if tag == "urlset":
            for element in root.findall(".//{*}loc"):
                page_url = self.normalize_url((element.text or "").strip())
                if page_url and self.enqueue_url(page_url):
                    discovered += 1
            self.log(f"   Sitemap {sitemap_url} queued {discovered} URLs.")
            return True

        return False

    def parse_text_sitemap(self, sitemap_url, text):
        discovered = 0
        for line in text.splitlines():
            page_url = self.normalize_url(line.strip())
            if page_url and self.enqueue_url(page_url):
                discovered += 1
        if discovered:
            self.log(f"   Text sitemap {sitemap_url} queued {discovered} URLs.")
        return discovered > 0

    def parse_html_sitemap(self, sitemap_url, html):
        soup = BeautifulSoup(html, "html.parser")
        hyperlinks = soup.select("a[href]")
        urls, _ = self.parse_links(hyperlinks, sitemap_url)
        discovered = 0
        for page_url in urls:
            if self.enqueue_url(page_url):
                discovered += 1
        if discovered:
            self.log(f"   HTML sitemap {sitemap_url} queued {discovered} URLs.")
        return discovered > 0

    def process_sitemap(self, sitemap_url, proxies):
        normalized_sitemap = self.normalize_url(sitemap_url)
        if not normalized_sitemap:
            return False

        with self.lock:
            if (
                normalized_sitemap in self.processed_sitemaps
                or normalized_sitemap in self.bad_sitemaps
                or normalized_sitemap in self.sitemap_fetch_inflight
            ):
                return False
            self.sitemap_fetch_inflight.add(normalized_sitemap)

        try:
            response = self.request_url(normalized_sitemap, proxies=proxies, timeout=min(self.request_timeout, 12))
            response.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                with self.lock:
                    self.bad_sitemaps.add(normalized_sitemap)
                self.log(f"   Ignoring missing sitemap {normalized_sitemap} (404).")
                return False
            return False
        except requests.RequestException:
            return False
        try:
            content_type = response.headers.get("content-type", "").lower()
            content, text = self.decode_sitemap_payload(normalized_sitemap, response)
            if content is None:
                with self.lock:
                    self.bad_sitemaps.add(normalized_sitemap)
                return False

            parsed_ok = False
            if "xml" in content_type or text.lstrip().startswith("<?xml") or text.lstrip().startswith("<urlset") or text.lstrip().startswith("<sitemapindex"):
                parsed_ok = self.parse_sitemap_xml(normalized_sitemap, content, proxies)

            if not parsed_ok and (normalized_sitemap.endswith(".txt") or "text/plain" in content_type):
                parsed_ok = self.parse_text_sitemap(normalized_sitemap, text)

            if not parsed_ok and ("html" in content_type or "<html" in text[:400].lower()):
                parsed_ok = self.parse_html_sitemap(normalized_sitemap, text)

            with self.lock:
                if parsed_ok:
                    self.processed_sitemaps.add(normalized_sitemap)
                else:
                    self.bad_sitemaps.add(normalized_sitemap)
            return parsed_ok
        finally:
            with self.lock:
                self.sitemap_fetch_inflight.discard(normalized_sitemap)

    def maybe_refill_queue(self):
        if not self.continuous_mode:
            return False

        now = time.time()
        
        with self.lock:
            queue_size = self.queue.qsize()
            
            # If queue has items, don't refill (let them be processed)
            if queue_size > 10:
                return False
            
            # If queue is small but not empty, wait longer before refill
            if queue_size > 0:
                if now - self.last_idle_refill < self.idle_reseed_delay:
                    return False
            
            # If queue is completely empty, refill IMMEDIATELY
            # Don't wait - this prevents the crawl from stopping
            if queue_size == 0:
                self.last_idle_refill = now
            else:
                # Queue has 1-10 items, check the delay
                if now - self.last_idle_refill < self.idle_reseed_delay:
                    return False
                self.last_idle_refill = now

        # Refill strategy: add unvisited seeds and discovered URLs
        recrawl_targets = []
        
        with self.lock:
            # Always add ALL seeds that haven't been visited yet
            for seed_url in self.starting_urls:
                if seed_url not in self.visited_urls:
                    recrawl_targets.append((seed_url, True))  # (url, is_seed)
            
            # Add up to 100 pagerank URLs that haven't been visited
            if self.pagerank_graph:
                discovered_urls = [url for url in list(self.pagerank_graph.keys())[:200] if url not in self.visited_urls]
                for url in discovered_urls[:100]:
                    recrawl_targets.append((url, False))  # (url, is_discovered)
        
        if not recrawl_targets:
            self.log("Cannot refill queue: all URLs exhausted.")
            return False
        
        # When refilling, DON'T clear visited_urls - only clear if we have no other choice
        # This prevents revisiting the same pages
        
        added_count = 0
        for url, is_seed in recrawl_targets:
            if self.requeue_url(url, is_seed=is_seed):
                added_count += 1
        
        if added_count > 0:
            self.log(f"🔄 Crawler queue refilled: added {added_count} URLs from {len(recrawl_targets)} available.")
            self.publish_status("indexing", f"Crawler queue refilled with {added_count} URLs.")
            return True
        
        return False

    def update_page_index(self, page_url, indexed_page):
        words = set(indexed_page["words"])
        fingerprint = indexed_page.get("content_fingerprint")

        with self.lock:
            existing_doc_id = self.url_to_doc_id.get(page_url)
            if existing_doc_id is None and fingerprint:
                existing_doc_id = self.content_fingerprints.get(fingerprint)

            if existing_doc_id is not None:
                doc_id = existing_doc_id
                previous_page = self.webpage_info.get(doc_id, {})
                previous_url = previous_page.get("url")
                if previous_url and previous_url != page_url:
                    self.url_to_doc_id.pop(previous_url, None)
                previous_words = self.doc_words.get(doc_id, set())
                for word in previous_words:
                    doc_ids = self.index.get(word)
                    if not doc_ids:
                        continue
                    doc_ids.discard(doc_id)
                    if not doc_ids:
                        del self.index[word]
            else:
                doc_id = self.doc_id_counter
                self.doc_id_counter += 1
                self.url_to_doc_id[page_url] = doc_id

            for word in words:
                self.index.setdefault(word, set()).add(doc_id)

            self.doc_words[doc_id] = words
            self.webpage_info[doc_id] = indexed_page
            if fingerprint:
                self.content_fingerprints[fingerprint] = doc_id
            self.url_to_doc_id[page_url] = doc_id

        return doc_id

    def maybe_save_snapshot(self, reason="periodic"):
        if self.crawl_count == 0:
            return False

        if reason == "periodic" and (self.crawl_count - self.last_saved_count) < self.save_every:
            return False

        if not self.save_lock.acquire(blocking=False):
            return False

        try:
            with self.lock:
                index_snapshot = {word: sorted(doc_ids) for word, doc_ids in self.index.items()}
                doc_snapshot = {doc_id: dict(info) for doc_id, info in self.webpage_info.items()}
                graph_snapshot = {url: set(links) for url, links in self.pagerank_graph.items()}
                crawl_count = self.crawl_count

            self.log(f"Reindexing after {crawl_count} crawled pages ({reason}).")
            idx_json, doc_json, state_json, docs_indexed, words_indexed = self.build_snapshot_payloads(
                index_snapshot,
                doc_snapshot,
                graph_snapshot,
                crawl_count,
            )
            limits_ok, limit_reason = self.enforce_data_limits(idx_json, doc_json, state_json)
            if not limits_ok:
                self.log(f"Stopping crawl because {limit_reason}.")
                self.publish_status("stopped", f"Crawl stopped because {limit_reason}.")
                self.stop_event.set()
                return False

            with open(self.idx_path, "w", encoding="utf-8") as handle:
                handle.write(idx_json)

            with open(self.doc_path, "w", encoding="utf-8") as handle:
                handle.write(doc_json)

            self.last_saved_count = crawl_count
            self.last_saved_at = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self.state_path, "w", encoding="utf-8") as handle:
                handle.write(state_json)

            self.log(f"Saved search snapshot with {docs_indexed} docs and {words_indexed} indexed terms.")
            self.publish_status(
                "ready",
                f"Index refreshed after {crawl_count} crawled pages.",
                {
                    "docs_indexed": docs_indexed,
                    "words_indexed": words_indexed,
                },
            )

            if self.save_callback:
                self.save_callback(
                    {
                        "crawl_count": crawl_count,
                        "docs_indexed": docs_indexed,
                        "words_indexed": words_indexed,
                        "idx_path": self.idx_path,
                        "doc_path": self.doc_path,
                        "saved_at": self.last_saved_at,
                    }
                )
            return True
        finally:
            self.save_lock.release()

    def parse_links(self, hyperlinks, current_url):
        urls = []
        hyperlink_connections = set()

        for hyperlink in hyperlinks:
            url = hyperlink.get("href", "")
            if not url or url.startswith("#"):
                continue
            absolute_url = urljoin(current_url, url)
            normalized = self.normalize_url(absolute_url)
            if not normalized:
                continue
            urls.append(normalized)
            hyperlink_connections.add(normalized)

        return urls, hyperlink_connections

    def extract_canonical_url(self, webpage, current_url):
        canonical_link = webpage.find("link", attrs={"rel": lambda value: value and "canonical" in str(value).lower()})
        if canonical_link and canonical_link.get("href"):
            return self.normalize_url(urljoin(current_url, canonical_link["href"]))
        return self.normalize_url(current_url)

    def parse_robot_directives(self, webpage, response):
        directives = set()

        header_value = response.headers.get("X-Robots-Tag", "")
        for part in header_value.split(","):
            directive = part.strip().lower()
            if directive:
                directives.add(directive)

        meta_tags = webpage.find_all("meta", attrs={"name": lambda value: value and value.lower() == "robots"})
        for meta_tag in meta_tags:
            content = meta_tag.get("content", "")
            for part in content.split(","):
                directive = part.strip().lower()
                if directive:
                    directives.add(directive)

        return directives

    def crawl_worker(self):
        while not self.stop_event.is_set():
            if self.should_stop():
                self.stop_event.set()
                break

            try:
                # FIXED: Shorter timeout so workers check stop_event more frequently
                # PriorityQueue returns tuple: (priority, url)
                priority_tuple, current_url = self.queue.get(timeout=0.5)
            except Empty:
                if self.stop_event.is_set():
                    break
                if self.maybe_refill_queue():
                    continue
                if self.continuous_mode:
                    if not self.sleep_with_stop(0.5):  # Check stop more frequently
                        break
                    continue
                break

            if self.stop_event.is_set():
                break

            try:
                with self.lock:
                    if current_url in self.visited_urls:
                        continue
                    self.visited_urls.add(current_url)
                    
                    # Track seed status for logging and depth assignment
                    is_seed = self.url_seed_map.get(current_url, False)
                    current_depth = self.url_depth_map.get(current_url, 0)
                
                if is_seed:
                    with self.lock:
                        self.seed_urls_crawled += 1
                        self.seed_urls_remaining = max(0, self.seed_urls_remaining - 1)

                self.log(f"Crawling: {current_url}" + (" [SEED]" if is_seed else ""))
                if not self.sleep_with_stop(random.uniform(self.min_delay, self.max_delay)):
                    break

                if self.stop_event.is_set():
                    break

                proxies = self.get_next_proxy()
                if proxies:
                    proxy_host = proxies["https"].split("@")[-1]
                    self.log(f"   Proxy: {proxy_host}")

                self.discover_domain_metadata(current_url, proxies)
                if not self.can_fetch(current_url):
                    self.log(f"   Skipping disallowed URL from robots.txt: {current_url}")
                    continue

                response = self.request_url(current_url, proxies=proxies)
                response.raise_for_status()
                if self.stop_event.is_set():
                    break

                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type:
                    self.log(f"   Skipping non-HTML response from {current_url}")
                    continue

                webpage = BeautifulSoup(response.content, "html.parser")
                final_url = self.normalize_url(response.url) or current_url
                canonical_url = self.extract_canonical_url(webpage, final_url) or final_url
                directives = self.parse_robot_directives(webpage, response)
                if "noindex" in directives:
                    self.log(f"   Skipping noindex page: {canonical_url}")
                    if "nofollow" in directives:
                        continue
                    hyperlinks = webpage.select("a[href]")
                    new_urls, hyperlink_connections = self.parse_links(hyperlinks, canonical_url)
                    with self.lock:
                        self.pagerank_graph[canonical_url] = hyperlink_connections
                        self.crawl_count += 1
                    self.record_domain_crawl(canonical_url)  # Track domain pages
                    for new_url in new_urls:
                        # Discovered URLs are not seeds, so is_seed=False
                        self.enqueue_url(new_url, is_seed=False, depth=current_depth + 1)
                    continue

                indexed_page = index_page(webpage, canonical_url)
                doc_id = self.update_page_index(canonical_url, indexed_page)

                hyperlinks = [] if "nofollow" in directives else webpage.select("a[href]")
                new_urls, hyperlink_connections = self.parse_links(hyperlinks, canonical_url)

                with self.lock:
                    self.known_urls.add(canonical_url)
                    self.visited_urls.add(canonical_url)
                    self.pagerank_graph[canonical_url] = hyperlink_connections
                    self.crawl_count += 1
                    crawl_count = self.crawl_count
                    docs_indexed = len(self.webpage_info)
                
                self.record_domain_crawl(canonical_url)  # Track domain pages

                for new_url in new_urls:
                    # Discovered URLs inherit the depth+1 from parent (seeds or discovered)
                    # but are marked as non-seeds (discovered=False)
                    self.enqueue_url(new_url, is_seed=False, depth=current_depth + 1)

                log_suffix = f" | depth: {current_depth}" + (" [SEED]" if is_seed else "")
                self.log(f"   Indexed doc #{doc_id} | total crawled: {crawl_count} | docs: {docs_indexed}{log_suffix}")
                self.publish_status("indexing", f"Crawled {crawl_count} pages so far.")
                self.maybe_save_snapshot(reason="periodic")
            except requests.RequestException as exc:
                self.log(f"   Request failed for {current_url}: {exc}")
            except Exception as exc:
                self.log(f"   Unexpected crawler error for {current_url}: {exc}")
            finally:
                self.queue.task_done()

    def run(self):
        self.log("")
        self.log(f"{self.crawler_name} is starting.")
        self.log(f"Workers: {self.num_workers} | save every: {self.save_every} pages")
        if self.crawl_limit > 0:
            self.log(f"Crawl limit: {self.crawl_limit}")
        else:
            self.log("Crawl limit: unlimited")

        resumed = self.load_resume_state()
        if resumed:
            self.log("Resuming crawler from the last saved crawl state.")
            self.publish_status("indexing", "Resuming crawler from the last saved crawl state.")
            # NEW: Check for newly added seed URLs
            self.check_for_new_seeds()
        else:
            self.publish_status("indexing", "Crawler service is starting up.")
            self.seed_queue()

        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = [executor.submit(self.crawl_worker) for _ in range(self.num_workers)]

            try:
                for future in futures:
                    # Use timeout so we can check stop_event periodically
                    try:
                        future.result(timeout=0.5)
                    except TimeoutError:
                        # Worker didn't finish in 0.5s, continue
                        pass
            except KeyboardInterrupt:
                # Ctrl+C pressed - graceful shutdown
                self.log("\n⚡ STOP SIGNAL: Ctrl+C pressed - stopping crawler...")
                self.stop_event.set()
                executor.shutdown(wait=False)
                for future in futures:
                    future.cancel()

        # Save state one last time before exiting
        self.log("Crawler is finishing in-flight work and saving the last snapshot.")
        self.maybe_save_snapshot(reason="final")
        self.publish_status("stopped", "Crawler service stopped.")
        self.log("✓ Crawler service stopped gracefully.")


def run_crawler_service(
    config=None,
    runtime_options=None,
    log_callback=None,
    status_callback=None,
    save_callback=None,
    stop_event=None,
):
    service = CrawlerService(
        config=config,
        runtime_options=runtime_options,
        log_callback=log_callback,
        status_callback=status_callback,
        save_callback=save_callback,
        stop_event=stop_event,
    )
    service.run()
    return service


def parse_args():
    parser = argparse.ArgumentParser(description="Aurora Search crawler service")
    parser.add_argument("--save-every", type=int, default=30, help="Save/reindex after this many crawled pages")
    parser.add_argument(
        "--continuous",
        dest="continuous",
        action="store_true",
        help="Keep reseeding known URLs so the crawler keeps running",
    )
    parser.add_argument(
        "--no-continuous",
        dest="continuous",
        action="store_false",
        help="Stop when the crawl frontier is exhausted",
    )
    parser.set_defaults(continuous=True)
    return parser.parse_args()


def main():
    args = parse_args()
    run_crawler_service(
        runtime_options={
            "save_every": args.save_every,
            "continuous": args.continuous,
        }
    )


if __name__ == "__main__":
    main()
