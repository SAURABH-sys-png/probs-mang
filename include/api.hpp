#pragma once

#include "primary.hpp"

#include <string>

void turn(Problem* obj);

std::string escape(const std::string& s);
std::string unescape(const std::string& s);
void emit(const std::string& tag, const std::string& payload = "");
