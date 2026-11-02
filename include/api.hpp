#pragma once

#include "primary.hpp"

#include <string>

void turn(Problem* obj);

// Wire format shared with ui/gui.py
//   commands come one per line, a value is the line after the command and
//   multi-line values are escaped (\\ \n \t \r).
//   replies are "\x1e<TAG> <payload>\n" lines, mixed with plain program output.
std::string escape(const std::string& s);
std::string unescape(const std::string& s);
void emit(const std::string& tag, const std::string& payload = "");
