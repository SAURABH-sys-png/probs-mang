#pragma once

#include "primary.hpp"

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace pqxx {
class connection;
}

class DB {
 public:
  explicit DB(const std::string& conn = con_str);
  ~DB();

  int create(Problem& p);
  bool read(int id, Problem& p);
  std::vector<Problem> read_all();
  bool update(const Problem& p);
  bool update_field(int id, const std::string& column, const std::string& value);
  bool remove(int id);
  std::map<std::string, int> activity();

 private:
  std::unique_ptr<pqxx::connection> cx;
};
