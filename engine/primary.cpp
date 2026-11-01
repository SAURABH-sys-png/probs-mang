#include "primary.hpp"
#include <pqxx/pqxx>
#include <cstdlib>
#include <filesystem>
#include <iostream>

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
  pqxx::connection cx(con_str);
  std::cout << "Database connected" << '\n';
  ppxx::work(cx);

}
