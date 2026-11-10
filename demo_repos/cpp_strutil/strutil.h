#pragma once

#include <string>
#include <vector>

namespace strutil {

// Remove whitespace from both ends of a string.
std::string trim(const std::string& text);

// Split a string on a delimiter character.
std::vector<std::string> split(const std::string& text, char delimiter);

// Convert ASCII letters to upper case.
std::string to_upper(const std::string& text);

}  // namespace strutil
