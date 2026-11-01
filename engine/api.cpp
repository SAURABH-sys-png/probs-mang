#include "api.hpp"

#include <iostream>
#include <string>

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
  

  while (true) {
    std::string input;
    std::getline(std::cin, input);


    if (input == end) {
      break;
    }
    else if (input == name) {
      std::getline(std::cin, in_name);
      // save it inot the object of the main qs object
      obj->set_name(in_name);
    }
    else if (input == code) {
      std::getline(std::cin, in_code);
      // save the code in the main object also 
      obj->set_code(in_code);
    }
    else if (input == test_cases) {
      std::getline(std::cin, in_test_cases);
      //make a file of test case
      obj->set_test_cases(in_test_cases);
    }
    else if (input == compile) {
      //execute the compilation function
      obj->check_compilation();
    }
    else if (input == run) {
      //execute run function 
      obj->check_runtime();
    }
    else if (input == submit) {
      //execute everything in handy
      obj->submit();
    }
}
  }
