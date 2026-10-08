

import random


for i in range(1,12001):
    #assign a file name based on the current iteration
    file_path = f"my_12k_files/file_{i}.txt"
        
    #keep track of the the current file
    ref_list = []

    with open(file_path, "w") as file:
            
        #creates the file and writes an arbitrary number of file references to it with 325 being a rare max
        for j in range(int(random.triangular(1, 325, 20))):

                #randomly generate a file number to be added
                num = random.randint(1,12000)

                #ensure that the file doesnt reference itself 
                while num == i or num in ref_list:
                    num = random.randint(1, 12000)

                #track what numbers are already in list avoid duplicate
                ref_list.append(num)

                #add references to the doc upon creation
                file.write("file_" + str(num) + ".txt\n")

print(f"Files have been created and written to.")

