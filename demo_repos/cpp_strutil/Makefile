CXX ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O1

build/test_strutil: strutil.cpp strutil.h tests/test_strutil.cpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) strutil.cpp tests/test_strutil.cpp -o build/test_strutil

.PHONY: test clean
test: build/test_strutil
	./build/test_strutil

clean:
	rm -rf build
