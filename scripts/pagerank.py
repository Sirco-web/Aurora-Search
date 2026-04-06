

def compute_pagerank(graph, damping_factor=0.85, max_iterations=100, tol=1.0e-6):
    # Build the set of all URLs
    all_nodes = set(graph.keys())
    for links in graph.values():
        all_nodes.update(links)
    num_nodes = len(all_nodes)
    # Initialize PageRank scores
    pagerank = {url: 1.0 / num_nodes for url in all_nodes}
    # Identify dangling nodes (nodes with no outgoing links)
    dangling_nodes = [url for url in all_nodes if url not in graph or len(graph[url]) == 0]
    # Iterative computation
    for iteration in range(max_iterations):
        new_pagerank = {}
        # Sum of PageRank scores from dangling nodes
        dangling_sum = damping_factor * sum(pagerank[node] for node in dangling_nodes) / num_nodes
        for url in all_nodes:
            rank = (1.0 - damping_factor) / num_nodes
            rank += dangling_sum
            # Sum contributions from incoming links
            for node in graph:
                if url in graph[node]:
                    out_degree = len(graph[node])
                    rank += damping_factor * pagerank[node] / out_degree
            new_pagerank[url] = rank
        # Check for convergence
        error = sum(abs(new_pagerank[url] - pagerank[url]) for url in all_nodes)
        if error < tol:
            break
        pagerank = new_pagerank
    for url in all_nodes:
        pagerank[url] = round(pagerank[url], 6)
    return pagerank
