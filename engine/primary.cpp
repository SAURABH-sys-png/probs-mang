#include "primary.hpp"
#include "db.hpp"
#include <pqxx/pqxx>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>

namespace fs = std::filesystem;

void Problem::set_name(std::string& nm) { name = nm; }

void Problem::set_code(std::string& cd) { code = cd; }

void Problem::set_test_cases(std::string& tc) { test_cases = tc; }

std::string Problem::check_compilation() {
  fs::path target_dir = fs::path(PROBS_MANG_SOURCE_DIR) / "test";
  std::string ans = "";
  try {
    fs::current_path(target_dir);
    std::cout << "Changed the directiory path" << '\n';
    std::string file_name = "./";
    file_name += name;
    file_name += ".cpp";
    std::string executable_command = "g++ " + file_name + " -o random";
    const char* c_str_pointer = executable_command.c_str();
    int res = std::system(c_str_pointer);
    ans = (res == 0) ? "Compilation succesful" : "NOt compiled";
  } catch (const fs::filesystem_error& e) {
    std::cout << "An error occured pls try again" << '\n';
  }

  return ans;
}

std::string Problem::check_runtime() {
  fs::path target_dir = fs::path(PROBS_MANG_SOURCE_DIR) / "test";
  std::string ans = "";
  try {
    fs::current_path(target_dir);
    std::cout << "Changes the director" << '\n';
    std::string executable_command_str =
        "g++ " + name + ".cpp -o tst && ./tst < input_" + name + ".txt";
    const char* c_str_pointer = executable_command_str.c_str();
    int res = std::system(c_str_pointer);
    ans = (res == 0) ? "Runtime succesful succesful" : "Runtime error occured";
  } catch (const fs::filesystem_error& e) {
    std::cout << "Runtime error" << '\n';
  }

  return ans;
}

void Problem::submit() {
  //updates the postgres db
  if (!save()) throw std::runtime_error("could not save the files of " + name);
  DB db(con_str);
  std::cout << "Database connected" << '\n';
  // update the stored row, or insert a new one if it is not there (anymore)
  if (id < 0 || !db.update(*this)) db.create(*this);
}

std::string Problem::code_path() const {
  return (fs::path(PROBS_MANG_SOURCE_DIR) / "test" / (name + ".cpp")).string();
}

std::string Problem::test_cases_path() const {
  return (fs::path(PROBS_MANG_SOURCE_DIR) / "test" / ("input_" + name + ".txt"))
      .string();
}

bool Problem::has_test_cases() const {
  std::error_code ec;
  return !name.empty() && fs::exists(test_cases_path(), ec);
}

bool Problem::save() {
  if (name.empty()) return false;
  std::error_code ec;
  fs::create_directories(fs::path(code_path()).parent_path(), ec);

  std::ofstream code_file(code_path(), std::ios::binary | std::ios::trunc);
  code_file << code;
  code_file.close();
  if (!code_file) return false;

  // check_runtime() reads input_<name>.txt, so it only exists when there are test cases
  if (test_cases.empty()) {
    fs::remove(test_cases_path(), ec);
    return true;
  }
  std::ofstream tc_file(test_cases_path(), std::ios::binary | std::ios::trunc);
  tc_file << test_cases;
  if (!test_cases.empty() && test_cases.back() != '\n') tc_file << '\n';
  tc_file.close();
  return static_cast<bool>(tc_file);
}

bool Problem::load_files() {
  std::ifstream code_file(code_path(), std::ios::binary);
  if (!code_file) return false;
  std::stringstream code_buf;
  code_buf << code_file.rdbuf();
  code = code_buf.str();

  test_cases.clear();
  std::ifstream tc_file(test_cases_path(), std::ios::binary);
  if (tc_file) {
    std::stringstream tc_buf;
    tc_buf << tc_file.rdbuf();
    test_cases = tc_buf.str();
  }
  return true;
}

std::string Problem::run_interactive() {
  fs::path target_dir = fs::path(PROBS_MANG_SOURCE_DIR) / "test";
  std::error_code ec;
  fs::current_path(target_dir, ec);
  if (ec) return "Runtime error: can not open " + target_dir.string();

  // The GUI drives us through a raw pty, switch it to line mode while the
  // program runs so that it gets whole lines and Ctrl-D works as EOF.
  termios saved{};
  bool tty = isatty(STDIN_FILENO) && tcgetattr(STDIN_FILENO, &saved) == 0;
  if (tty) {
    termios line_mode = saved;
    line_mode.c_lflag |= ICANON;
    line_mode.c_lflag &= ~(ECHO | ECHONL);
    line_mode.c_cc[VEOF] = 4;
    tcsetattr(STDIN_FILENO, TCSANOW, &line_mode);
  }

  std::string executable_command_str = "g++ " + name + ".cpp -o tst && ./tst";
  int res = std::system(executable_command_str.c_str());

  if (tty) {
    // drop whatever the program did not read so it is not taken as a command
    tcflush(STDIN_FILENO, TCIFLUSH);
    tcsetattr(STDIN_FILENO, TCSANOW, &saved);
  }

  if (res == 0) return "Runtime succesful";
  if (res != -1 && WIFEXITED(res))
    return "Runtime error occured (exit code " + std::to_string(WEXITSTATUS(res)) + ")";
  return "Runtime error occured";
}

namespace {

bool parse_int(const std::string& value, std::optional<int>& out) {
  if (value.empty()) {
    out.reset();
    return true;
  }
  try {
    size_t used = 0;
    int v = std::stoi(value, &used);
    if (used != value.size()) return false;
    out = v;
    return true;
  } catch (const std::exception&) {
    return false;
  }
}

std::string trim(const std::string& s) {
  size_t b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos) return "";
  size_t e = s.find_last_not_of(" \t\r\n");
  return s.substr(b, e - b + 1);
}

}  // namespace

bool Problem::set_field(const std::string& key, const std::string& value) {
  if (key == "id") {
    std::optional<int> v;
    if (!parse_int(value, v)) return false;
    id = v.value_or(-1);
  } else if (key == "date_of_doing") {
    date_of_doing = value;
  } else if (key == "comment") {
    comment = value;
  } else if (key == "is_completed") {
    is_completed = (value == "1" || value == "true" || value == "t" || value == "yes");
  } else if (key == "platform") {
    platform = value;
  } else if (key == "problem_type") {
    problem_type = value;
  } else if (key == "difficulty") {
    difficulty = value;
  } else if (key == "time_taken_minutes") {
    return parse_int(value, time_taken_minutes);
  } else if (key == "time_complexity") {
    time_complexity = value;
  } else if (key == "space_complexity") {
    space_complexity = value;
  } else if (key == "tags") {
    tags.clear();
    std::stringstream ss(value);
    std::string tag;
    while (std::getline(ss, tag, ',')) {
      tag = trim(tag);
      if (!tag.empty()) tags.push_back(tag);
    }
  } else if (key == "revision_count") {
    std::optional<int> v;
    if (!parse_int(value, v)) return false;
    revision_count = v.value_or(0);
  } else if (key == "importance_rating") {
    return parse_int(value, importance_rating);
  } else {
    return false;
  }
  return true;
}
