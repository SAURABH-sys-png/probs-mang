#include "api.hpp"
#include "primary.hpp"
#include "data_analysis.hpp"

#include <iostream>

int main(){
  std::ios_base::sync_with_stdio(false);
  std::cin.tie(NULL);
  // make a turn 
  Problem my_code;
  turn(&my_code);
  return 0;
}
