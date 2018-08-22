Note there is some weird interaction going on between these testcases,
the way TCF imports stuff and unittest discover.

Thus, they won't work under

$ python -m unittest discover

However, they work ok running them from the shell:

$ for v in test_*.py; do $v; done
