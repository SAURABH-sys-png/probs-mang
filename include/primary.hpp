#pragma once

#include <string>
std::string con_str = "host=localhost "
            "port=5433 "
            "dbname=programs "
            "user=programshandler "
            "password=0008";
class Problem {
 public:
  std::string name = "";
  std::string code = "";
  std::string test_cases = "";

  void set_name(std::string& nm);
  void set_code(std::string& cd);
  void set_test_cases(std::string& tc);
  std::string check_compilation();
  std::string check_runtime();
  void submit();
};
