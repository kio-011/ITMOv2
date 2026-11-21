CXX ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O2

bank: main.cpp bank.cpp bank.h
	$(CXX) $(CXXFLAGS) -o bank main.cpp bank.cpp

test: tests.cpp bank.cpp bank.h
	$(CXX) $(CXXFLAGS) -o tests tests.cpp bank.cpp
	./tests

clean:
	rm -f bank tests audit.log

.PHONY: test clean
