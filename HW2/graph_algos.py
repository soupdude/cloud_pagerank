from collections import deque


def page_rank(out_graph, in_graph, tolerance=0.005):
    """
    Computes PageRank using: PR(A) = 0.15/n + 0.85 * sum(PR(Ti)/C(Ti))
    where T1..Tn are pages linking to A, and C(Ti) is the out-degree of Ti.

    Iterates until the total sum of PageRanks across all pages changes
    by no more than 0.5% (tolerance) between iterations.
    """
    n = len(out_graph)
    ranks = {node: 1.0 / n for node in out_graph}  # initial rank: 1/n each

    prev_sum = sum(ranks.values())
    iteration = 0

    while True:
        iteration += 1
        new_ranks = {}

        for page in out_graph:
            total = 0.15 / n

            # Sum contributions from every page T that links to `page`
            for t in in_graph.get(page, []):
                c_t = len(out_graph[t])  # C(T): number of outgoing links from T
                if c_t > 0:
                    total += 0.85 * (ranks[t] / c_t)

            new_ranks[page] = total

        current_sum = sum(new_ranks.values())

        # Check if the sum of pageranks changed by more than 0.5%
        percent_change = abs(current_sum - prev_sum) / prev_sum
        max_diff = max(abs(new_ranks[p] - ranks[p]) for p in new_ranks)
        ranks = new_ranks
        prev_sum = current_sum

        if percent_change <= tolerance and max_diff < 1e-9:
            print(f"Converged after {iteration} iterations "
                  f"(sum changed by {percent_change*100:.4f}%)")
            break

    return ranks

def best_closeness(out_graph):
    nodes = list(out_graph)
    idx = {name: i for i, name in enumerate(nodes)}
    n = len(nodes)
    adj = [[idx[v] for v in out_graph[u]] for u in nodes]

    best, best_score = None, -1.0
    for src in range(n):
        dist = [-1] * n
        dist[src] = 0
        frontier = [src]
        total = reached = d = 0
        while frontier:
            d += 1
            nxt = []
            for u in frontier:
                for v in adj[u]:
                    if dist[v] < 0:
                        dist[v] = d
                        nxt.append(v)
            total += d * len(nxt)
            reached += len(nxt)
            frontier = nxt
        score = (reached / total) * (reached / (n - 1)) if total else 0.0
        if score > best_score:
            best, best_score = nodes[src], score
    return best, best_score