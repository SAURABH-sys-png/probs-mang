#include "db.hpp"

#include <pqxx/pqxx>

#include <optional>
#include <stdexcept>

namespace {

const char* const kSelect =
    "SELECT id, name, date_of_doing::text, comment, is_completed, platform, "
    "problem_type, difficulty, time_taken_minutes, time_complexity, "
    "space_complexity, array_to_string(tags, ','), revision_count, "
    "importance_rating FROM problems";

std::optional<std::string> opt(const std::string& s) {
  if (s.empty()) return std::nullopt;
  return s;
}

std::string join_tags(const std::vector<std::string>& tags) {
  std::string out;
  for (const auto& t : tags) {
    if (t.empty()) continue;
    if (!out.empty()) out += ',';
    out += t;
  }
  return out;
}

std::string text(const pqxx::field& f) {
  return f.is_null() ? std::string{} : f.as<std::string>();
}

Problem from_row(const pqxx::row& r) {
  Problem p;
  p.id = r[0].as<int>();
  p.name = text(r[1]);
  p.date_of_doing = text(r[2]);
  p.comment = text(r[3]);
  p.is_completed = !r[4].is_null() && r[4].as<bool>();
  p.platform = text(r[5]);
  p.problem_type = text(r[6]);
  p.difficulty = text(r[7]);
  if (!r[8].is_null()) p.time_taken_minutes = r[8].as<int>();
  p.time_complexity = text(r[9]);
  p.space_complexity = text(r[10]);
  p.set_field("tags", text(r[11]));
  p.revision_count = r[12].is_null() ? 0 : r[12].as<int>();
  if (!r[13].is_null()) p.importance_rating = r[13].as<int>();
  return p;
}

// all the columns the problem owns, in $1..$15 order
pqxx::params row_params(const Problem& p) {
  pqxx::params prm;
  prm.append(p.name);
  prm.append(opt(p.date_of_doing));
  prm.append(p.code_path());
  prm.append(p.has_test_cases() ? std::optional<std::string>(p.test_cases_path())
                                : std::nullopt);
  prm.append(opt(p.comment));
  prm.append(p.is_completed);
  prm.append(opt(p.platform));
  prm.append(opt(p.problem_type));
  prm.append(opt(p.difficulty));
  prm.append(p.time_taken_minutes);
  prm.append(opt(p.time_complexity));
  prm.append(opt(p.space_complexity));
  prm.append(opt(join_tags(p.tags)));
  prm.append(p.revision_count);
  prm.append(p.importance_rating);
  return prm;
}

// SQL expression that turns the text parameter $2 into the column's type
std::optional<std::string> column_cast(const std::string& column) {
  if (column == "name" || column == "file_path") return "$2";
  if (column == "date_of_doing") return "COALESCE(NULLIF($2, '')::date, CURRENT_DATE)";
  if (column == "is_completed") return "COALESCE(NULLIF($2, '')::boolean, FALSE)";
  if (column == "revision_count") return "COALESCE(NULLIF($2, '')::integer, 0)";
  if (column == "time_taken_minutes") return "NULLIF($2, '')::integer";
  if (column == "importance_rating") return "NULLIF($2, '')::smallint";
  if (column == "tags") return "string_to_array(NULLIF($2, ''), ',')";
  if (column == "testcases_path" || column == "comment" || column == "platform" ||
      column == "problem_type" || column == "difficulty" ||
      column == "time_complexity" || column == "space_complexity")
    return "NULLIF($2, '')";
  return std::nullopt;
}

}  // namespace

DB::DB(const std::string& conn)
    : cx(std::make_unique<pqxx::connection>(conn + " connect_timeout=5")) {}

DB::~DB() = default;

int DB::create(Problem& p) {
  pqxx::work tx(*cx);
  int id = tx.exec(
                 "INSERT INTO problems (name, date_of_doing, file_path, "
                 "testcases_path, comment, is_completed, platform, problem_type, "
                 "difficulty, time_taken_minutes, time_complexity, "
                 "space_complexity, tags, revision_count, importance_rating) "
                 "VALUES ($1, COALESCE($2::date, CURRENT_DATE), $3, $4, $5, $6, "
                 "$7, $8, $9, $10, $11, $12, string_to_array($13, ','), $14, $15) "
                 "RETURNING id",
                 row_params(p))
               .one_field()
               .as<int>();
  tx.commit();
  p.id = id;
  return id;
}

bool DB::read(int id, Problem& p) {
  pqxx::read_transaction tx(*cx);
  auto res = tx.exec(std::string(kSelect) + " WHERE id = $1", pqxx::params{id});
  if (res.empty()) return false;
  Problem loaded = from_row(res[0]);
  // keep code / test cases already held by p
  loaded.code = p.code;
  loaded.test_cases = p.test_cases;
  p = loaded;
  return true;
}

std::vector<Problem> DB::read_all() {
  pqxx::read_transaction tx(*cx);
  std::vector<Problem> all;
  for (const auto& r : tx.exec(std::string(kSelect) +
                               " ORDER BY date_of_doing DESC, id DESC")) {
    all.push_back(from_row(r));
  }
  return all;
}

bool DB::update(const Problem& p) {
  pqxx::work tx(*cx);
  pqxx::params prm = row_params(p);
  prm.append(p.id);
  auto res = tx.exec(
      "UPDATE problems SET name = $1, "
      "date_of_doing = COALESCE($2::date, date_of_doing), file_path = $3, "
      "testcases_path = $4, comment = $5, is_completed = $6, platform = $7, "
      "problem_type = $8, difficulty = $9, time_taken_minutes = $10, "
      "time_complexity = $11, space_complexity = $12, "
      "tags = string_to_array($13, ','), revision_count = $14, "
      "importance_rating = $15 WHERE id = $16",
      prm);
  tx.commit();
  return res.affected_rows() > 0;
}

bool DB::update_field(int id, const std::string& column, const std::string& value) {
  auto cast = column_cast(column);
  if (!cast) throw std::invalid_argument("unknown column: " + column);
  if ((column == "name" || column == "file_path") && value.empty())
    throw std::invalid_argument(column + " can not be empty");
  pqxx::work tx(*cx);
  auto res = tx.exec("UPDATE problems SET " + column + " = " + *cast +
                         " WHERE id = $1",
                     pqxx::params{id, value});
  tx.commit();
  return res.affected_rows() > 0;
}

bool DB::remove(int id) {
  pqxx::work tx(*cx);
  auto res = tx.exec("DELETE FROM problems WHERE id = $1", pqxx::params{id});
  tx.commit();
  return res.affected_rows() > 0;
}

std::map<std::string, int> DB::activity() {
  pqxx::read_transaction tx(*cx);
  std::map<std::string, int> counts;
  for (const auto& r : tx.exec("SELECT date_of_doing::text, count(*) FROM problems "
                               "GROUP BY date_of_doing")) {
    counts[r[0].as<std::string>()] = r[1].as<int>();
  }
  return counts;
}
