#include <iostream>
#include <string>
#include <vector>

#include "../strutil.h"

static int failures = 0;

template <typename T>
void expect_eq(const T& actual, const T& expected, const std::string& name) {
    if (actual == expected) {
        std::cout << "ok   " << name << "\n";
    } else {
        std::cout << "FAIL " << name << "\n";
        ++failures;
    }
}

int main() {
    using namespace strutil;

    expect_eq(trim("  hello  "), std::string("hello"), "trim removes spaces on both sides");
    expect_eq(trim("hello"), std::string("hello"), "trim leaves a clean string alone");
    expect_eq(trim("\t a b \n"), std::string("a b"), "trim keeps inner spaces");
    expect_eq(trim("   "), std::string(""), "trim of only whitespace is empty");
    expect_eq(trim("x"), std::string("x"), "trim of one character");

    expect_eq(split("a,b,c", ','), std::vector<std::string>{"a", "b", "c"}, "split on commas");
    expect_eq(split("abc", ','), std::vector<std::string>{"abc"}, "split without delimiter");

    expect_eq(to_upper("MixEd 1"), std::string("MIXED 1"), "to_upper");

    if (failures > 0) {
        std::cout << failures << " test(s) failed\n";
        return 1;
    }
    std::cout << "all tests passed\n";
    return 0;
}
