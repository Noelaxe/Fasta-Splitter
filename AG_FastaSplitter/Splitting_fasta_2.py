def split_fasta(input_file_name, output_file_name, limit_per_file):

    limit = limit_per_file  
    inputfile = input_file_name
    outname = output_file_name
    
    outname = outname+"_Parts_"
    tempfile = outname + "0.fasta"

    file2 = open(tempfile, "w")
    count = 0

    with open(inputfile, "r") as file1:
        for line in file1:
            if line[0] == ">" and count % limit == 0:
                file2.close()
                file2 = open(outname + str((count // limit) + 1) + ".fasta", "w") 
                
            if line[0] == ">":
                count += 1
                
            file2.write(line)

    file2.close() 
