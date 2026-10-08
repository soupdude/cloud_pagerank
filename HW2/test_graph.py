from graph_algos import page_rank, best_closeness

def test_pagerank_cycle():
    out_g = {"A": ["B"], "B": ["C"], "C": ["A"]}
    in_g  = {"A": ["C"], "B": ["A"], "C": ["B"]}
    ranks = page_rank(out_g, in_g)
    assert all(abs(r - 1/3) < 1e-6 for r in ranks.values())

def test_pagerank_more_inlinks_ranks_higher():
    # B and C both point to A, A points to B
    out_g = {"A": ["B"], "B": ["A"], "C": ["A"]}
    in_g  = {"A": ["B", "C"], "B": ["A"], "C": []}
    ranks = page_rank(out_g, in_g)
    assert ranks["A"] > ranks["B"] > ranks["C"]
    
def test_closeness_star():
    # hub reaches everyone in 1 step, spokes link back to the hub
    out_g = {"hub": ["a", "b", "c"], "a": ["hub"], "b": ["hub"], "c": ["hub"]}
    assert best_closeness(out_g)[0] == "hub"

