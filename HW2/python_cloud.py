from google.cloud import storage
from graph_algos import page_rank, best_closeness
import time

PREFIX = "12k-files/"

client = storage.Client(project="project-f131ec20-0df6-4cfa-bf0")
bucket = client.bucket("cs528-12kfiles-bucket-thomas")

list_of_files = bucket.list_blobs(prefix=PREFIX)

in_graph = {}
in_avg = 0
in_min = 325
in_max = 0
in_median_list = []
in_quintile = [0, 0, 0, 0, 0]

out_graph = {}
out_avg = 0
out_min = 325
out_max = 0
out_median_list = []
out_quintile = [0, 0, 0, 0, 0]

node_out_in = {}


def initialize_graph():

    for n in range(1, 12001):
        node_out_in[f"file_{n}.txt"] = [0, 0]  # [outgoing, incoming]
        in_graph[f"file_{n}.txt"] = []
        out_graph[f"file_{n}.txt"] = []


    #Build the Graph from the files in the bucket
    for file in bucket.list_blobs(prefix=PREFIX):
        file_name = file.name[len(PREFIX):]
        if not file_name:  # Skip the prefix itself
            continue
        

        # Download the file content
        content = file.download_as_text()
        
        if file_name.endswith("00.txt"):
            print("downloaded", file_name)

        # Split the content into lines and add them to the graph, 
        # counts the number of links for each file, 
        # increments out node for eaach link,
        #  and increments the inode for the files that are reference
        for line in content.splitlines():
            target = line.strip()
            if not target:  # Skip empty lines
                continue

            out_graph[file_name].append(target)
            in_graph[target].append(file_name)
            node_out_in[target][1] += 1
            node_out_in[file_name][0] += 1

t0 = time.perf_counter()
initialize_graph()
total_edges = sum(len(v) for v in out_graph.values())
if total_edges == 0:
    raise SystemExit("No links were read. Check PREFIX and the bucket name.")
t1 = time.perf_counter()
print(len(out_graph), sum(len(v) for v in out_graph.values()))   # sanity check
ranks = page_rank(out_graph, in_graph)
t2 = time.perf_counter()

# Sort by rank descending, show top 5
top_pages = sorted(ranks.items(), key=lambda x: x[1], reverse=True)[:5]
print("\nTop 5 pages by PageRank:")
for file_name, score in top_pages:
    print(f"{file_name}: {score:.8f}")

# Sanity check: ranks should sum to ~1.0
print(f"\nSum of all ranks (should be ~1.0): {sum(ranks.values())}")

# Save full results to file
with open("pagerank.txt", "w") as f:
    for file_name, score in sorted(ranks.items(), key=lambda x: x[1], reverse=True):
        f.write(f"{file_name}: {score:.8f}\n")

#performs statistics calculations for the incoming links
for file, counts in node_out_in.items():
    in_count = counts[1]
    in_avg += in_count
    if in_count < in_min:
        in_min = in_count
    if in_count > in_max:
        in_max = in_count 
    in_median_list.append(in_count)

#perform statistics calculations for the outgoing links
for file, counts in node_out_in.items():
    out_count = counts[0]
    out_avg += out_count
    if out_count < out_min:
        out_min = out_count
    if out_count > out_max:
        out_max = out_count
    out_median_list.append(out_count)

#prepare median list for median calculation
in_median_list = sorted(in_median_list)
out_median_list = sorted(out_median_list)


#quintile calculations for incoming links
for n in range(1, 6):
    in_quintile[n-1] = in_median_list[(len(in_median_list) * n) // 5 - 1]
    out_quintile[n-1] = out_median_list[(len(out_median_list) * n) // 5 - 1]
    

#Output the graph statistics
print(len(in_graph))

print(f"Incoming Average: {in_avg/len(in_graph)}") 
print(f"Incoming Min: {in_min}")
print(f"Incoming Max: {in_max}")
print(f"Incoming Median: {in_median_list[len(in_median_list)//2]}")
print(f"Incoming Quintiles: {in_quintile}")


print(f"Outgoing Average: {out_avg/len(out_graph)}")
print(f"Outgoing Min: {out_min}")
print(f"Outgoing Max: {out_max}")
print(f"Outgoing Median: {out_median_list[len(out_median_list)//2]}")
print(f"Outgoing Quintiles: {out_quintile}")

file_path = "graph.txt"

with open(file_path, "w") as file:
    for key, values in out_graph.items():
        file.write(f"{key}: {', '.join(values)}\n")

t3 = time.perf_counter()
best_node, best_score = best_closeness(out_graph)
t4 = time.perf_counter()
print(f"Best closeness: {best_node} ({best_score:.6f})")
print(f"Download+graph: {t1-t0:.1f}s | PageRank: {t2-t1:.1f}s | Closeness: {t4-t3:.1f}s")