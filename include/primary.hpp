#pragma once

#include <optional>
#include <string>
#include <vector>
inline std::string con_str = "host=localhost "
            "port=5433 "
            "dbname=programs "
            "user=programhandler "
            "password=0008";
class Problem {
 public:
  std::string name = "";
  std::string code = "";
  std::string test_cases = "";

  int id = -1;
  std::string date_of_doing = "";
  std::string comment = "";
  bool is_completed = false;
  std::string platform = "";
  std::string problem_type = "";
  std::string difficulty = "";
  std::optional<int> time_taken_minutes;
  std::string time_complexity = "";
  std::string space_complexity = "";
  std::vector<std::string> tags;
  int revision_count = 0;
  std::optional<int> importance_rating;

  void set_name(std::string& nm);
  void set_code(std::string& cd);
  void set_test_cases(std::string& tc);
  std::string check_compilation();
  std::string check_runtime();
  void submit();

  std::string code_path() const;
  std::string test_cases_path() const;
  bool has_test_cases() const;
  bool save();
  bool load_files();
  std::string run_interactive();
  bool set_field(const std::string& key, const std::string& value);
};
