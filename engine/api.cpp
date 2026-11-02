#include "api.hpp"
#include "db.hpp"

#include <exception>
#include <filesystem>
#include <iostream>
#include <string>

namespace {

bool valid_name(const std::string& nm) {
  if (nm.empty()) return false;
  for (char c : nm) {
    bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-';
    if (!ok) return false;
  }
  return true;
}

bool parse_id(const std::string& s, int& id) {
  try {
    size_t used = 0;
    id = std::stoi(s, &used);
    return used == s.size() && id >= 0;
  } catch (const std::exception&) {
    return false;
  }
}

// "@@ROW" line: tab separated key=value pairs, values escaped
void emit_row(const Problem& p) {
  auto opt_int = [](const std::optional<int>& v) {
    return v ? std::to_string(*v) : std::string{};
  };
  std::string tags;
  for (const auto& t : p.tags) tags += (tags.empty() ? "" : ",") + t;
  std::string line;
  auto kv = [&line](const std::string& k, const std::string& v) {
    if (!line.empty()) line += '\t';
    line += k + "=" + escape(v);
  };
  kv("id", std::to_string(p.id));
  kv("name", p.name);
  kv("date_of_doing", p.date_of_doing);
  kv("file_path", p.code_path());
  kv("testcases_path", p.has_test_cases() ? p.test_cases_path() : "");
  kv("comment", p.comment);
  kv("is_completed", p.is_completed ? "true" : "false");
  kv("platform", p.platform);
  kv("problem_type", p.problem_type);
  kv("difficulty", p.difficulty);
  kv("time_taken_minutes", opt_int(p.time_taken_minutes));
  kv("time_complexity", p.time_complexity);
  kv("space_complexity", p.space_complexity);
  kv("tags", tags);
  kv("revision_count", std::to_string(p.revision_count));
  kv("importance_rating", opt_int(p.importance_rating));
  emit("ROW", line);
}

// split "key=value" (value escaped)
bool split_field(const std::string& line, std::string& key, std::string& value) {
  size_t eq = line.find('=');
  if (eq == std::string::npos || eq == 0) return false;
  key = line.substr(0, eq);
  value = unescape(line.substr(eq + 1));
  return true;
}

}  // namespace

std::string escape(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (char c : s) {
    switch (c) {
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\t': out += "\\t"; break;
      case '\r': out += "\\r"; break;
      default: out += c;
    }
  }
  return out;
}

std::string unescape(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (size_t i = 0; i < s.size(); ++i) {
    if (s[i] != '\\' || i + 1 == s.size()) {
      out += s[i];
      continue;
    }
    char c = s[++i];
    switch (c) {
      case 'n': out += '\n'; break;
      case 't': out += '\t'; break;
      case 'r': out += '\r'; break;
      default: out += c;
    }
  }
  return out;
}

void emit(const std::string& tag, const std::string& payload) {
  // ROW / CODE / TESTCASES come escaped already, messages are trimmed and
  // escaped here so a multi-line error still is one reply line
  std::string line = payload;
  if (tag != "ROW" && tag != "CODE" && tag != "TESTCASES") {
    size_t end = line.find_last_not_of(" \r\n");
    line = escape(end == std::string::npos ? "" : line.substr(0, end + 1));
  }
  std::cout << '\x1e' << tag << ' ' << line << std::endl;
}

void turn(Problem* obj) {
  std::string in_name = "";
  std::string in_code = "";
  std::string in_test_cases = "";

  std::string API_inputs = "";
  std::string st = "START";
  std::string end = "END";
  std::string name = "NAME";
  std::string code = "CODE";
  std::string test_cases = "TESTCASES";
  std::string compile = "COMPILE";
  std::string run = "RUN";
  std::string submit = "SUBMIT";

  // crud / helper commands used by the gui
  std::string save = "SAVE";            // write <name>.cpp and input_<name>.txt
  std::string run_manual = "RUNI";      // run with input typed in the terminal
  std::string field = "FIELD";          // next line: key=value (metadata)
  std::string load = "LOAD";            // next line: id   -> ROW, CODE, TESTCASES
  std::string list = "LIST";            // every row       -> ROW...
  std::string update = "UPDATE";        // next lines: id, key=value
  std::string remove = "DELETE";        // next line: id
  std::string activity = "ACTIVITY";    // problems per day -> DAY date count
  std::string reset = "NEW";            // forget the current problem
  std::string info = "INFO";            // paths used by the backend

  // flush after every write, the gui shows output as it comes
  std::cout << std::unitbuf;

  while (true) {
    std::string input;
    std::getline(std::cin, input);
    if (!std::cin) {
      break;
    }
    if (!input.empty() && input.back() == '\r') {
      input.pop_back();
    }

    if (input == end) {
      break;
    }
    else if (input == name) {
      std::getline(std::cin, in_name);
      // save it inot the object of the main qs object
      if (valid_name(in_name)) {
        obj->set_name(in_name);
      } else {
        emit("ERR", "invalid name '" + in_name + "', use only letters, digits, _ and -");
      }
    }
    else if (input == code) {
      std::getline(std::cin, in_code);
      in_code = unescape(in_code);
      // save the code in the main object also
      obj->set_code(in_code);
    }
    else if (input == test_cases) {
      std::getline(std::cin, in_test_cases);
      in_test_cases = unescape(in_test_cases);
      //make a file of test case
      obj->set_test_cases(in_test_cases);
    }
    else if (input == compile) {
      //execute the compilation function
      emit("RESULT", obj->check_compilation());
    }
    else if (input == run) {
      //execute run function
      if (obj->has_test_cases()) {
        emit("RESULT", obj->check_runtime());
      } else {
        emit("INFO", "no test cases, type the input in the terminal (Ctrl-D = EOF)");
        emit("INTERACTIVE");
        emit("RESULT", obj->run_interactive());
      }
    }
    else if (input == submit) {
      //execute everything in handy
      try {
        obj->submit();
        emit("ID", std::to_string(obj->id));
        emit("OK", "saved '" + obj->name + "' to the database (id " +
                       std::to_string(obj->id) + ")");
      } catch (const std::exception& e) {
        emit("ERR", std::string("database: ") + e.what());
      }
    }
    else if (input == save) {
      if (obj->save()) {
        emit("OK", "saved " + obj->code_path());
      } else {
        emit("ERR", "could not save the files of '" + obj->name + "'");
      }
    }
    else if (input == run_manual) {
      emit("INTERACTIVE");
      emit("RESULT", obj->run_interactive());
    }
    else if (input == field) {
      std::string line, key, value;
      std::getline(std::cin, line);
      if (!split_field(line, key, value) || !obj->set_field(key, value)) {
        emit("ERR", "bad field '" + line + "'");
      }
    }
    else if (input == load) {
      std::string line;
      std::getline(std::cin, line);
      int id = -1;
      try {
        DB db(con_str);
        if (!parse_id(line, id) || !db.read(id, *obj)) {
          emit("ERR", "no problem with id '" + line + "'");
        } else {
          if (!obj->load_files()) emit("WARN", "missing file " + obj->code_path());
          emit_row(*obj);
          emit("CODE", escape(obj->code));
          emit("TESTCASES", escape(obj->test_cases));
        }
      } catch (const std::exception& e) {
        emit("ERR", std::string("database: ") + e.what());
      }
    }
    else if (input == list) {
      try {
        DB db(con_str);
        for (const auto& p : db.read_all()) emit_row(p);
        emit("OK", "listed");
      } catch (const std::exception& e) {
        emit("ERR", std::string("database: ") + e.what());
      }
    }
    else if (input == update) {
      std::string id_line, line, key, value;
      std::getline(std::cin, id_line);
      std::getline(std::cin, line);
      int id = -1;
      try {
        if (!parse_id(id_line, id) || !split_field(line, key, value)) {
          emit("ERR", "bad update '" + id_line + "' '" + line + "'");
        } else if (DB(con_str).update_field(id, key, value)) {
          emit("OK", "updated " + key + " of problem " + id_line);
        } else {
          emit("ERR", "no problem with id " + id_line);
        }
      } catch (const std::exception& e) {
        emit("ERR", std::string("database: ") + e.what());
      }
    }
    else if (input == remove) {
      std::string line;
      std::getline(std::cin, line);
      int id = -1;
      try {
        if (!parse_id(line, id)) {
          emit("ERR", "bad id '" + line + "'");
        } else if (DB(con_str).remove(id)) {
          emit("OK", "deleted problem " + line);
        } else {
          emit("ERR", "no problem with id " + line);
        }
      } catch (const std::exception& e) {
        emit("ERR", std::string("database: ") + e.what());
      }
    }
    else if (input == activity) {
      try {
        DB db(con_str);
        for (const auto& [day, count] : db.activity()) {
          emit("DAY", day + " " + std::to_string(count));
        }
        emit("OK", "activity");
      } catch (const std::exception& e) {
        emit("ERR", std::string("database: ") + e.what());
      }
    }
    else if (input == reset) {
      *obj = Problem{};
    }
    else if (input == info) {
      emit("INFO", std::string("test_dir=") +
                       (std::filesystem::path(PROBS_MANG_SOURCE_DIR) / "test").string());
    }
    else {
      emit("ERR", "unknown command '" + input + "'");
    }
    emit("DONE", input);
}
  }
