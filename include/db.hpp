#pragma once

#include "primary.hpp"

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace pqxx {
class connection;
}

// CRUD operations on the `problems` table.
// Every method throws (pqxx / std exceptions) on failure.
class DB {
 public:
  explicit DB(const std::string& conn = con_str);
  ~DB();

  // INSERT, fills p.id with the new id and returns it
  int create(Problem& p);
  // SELECT by id, fills the metadata of p (not code / test cases), false if missing
  bool read(int id, Problem& p);
  // SELECT every row, newest first
  std::vector<Problem> read_all();
  // UPDATE every column of the row p.id, false if missing
  bool update(const Problem& p);
  // UPDATE a single column of the row, false if missing
  bool update_field(int id, const std::string& column, const std::string& value);
  // DELETE by id, false if missing
  bool remove(int id);
  // number of problems per date_of_doing (YYYY-MM-DD)
  std::map<std::string, int> activity();

 private:
  std::unique_ptr<pqxx::connection> cx;
};
