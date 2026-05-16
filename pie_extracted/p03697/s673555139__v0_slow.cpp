#include <algorithm>

#include <bitset>

#include <complex>

#include <deque>

#include <exception>

#include <fstream>

#include <functional>

#include <iomanip>

#include <ios>

#include <iosfwd>

#include <iostream>

#include <istream>

#include <iterator>

#include <limits>

#include <list>

#include <locale>

#include <map>

#include <memory>

#include <new>

#include <numeric>

#include <ostream>

#include <queue>

#include <set>

#include <sstream>

#include <stack>

#include <stdexcept>

#include <streambuf>

#include <string>

#include <typeinfo>

#include <utility>

#include <valarray>

#include <vector>



#define REP(i, m, n) for(int i=int(m);i<int(n);i++)

#define EACH(i, c) for (auto &(i): c)

#define all(c) begin(c),end(c)

#define EXIST(s, e) ((s).find(e)!=(s).end())

#define SORT(c) sort(begin(c),end(c))

#define pb emplace_back

#define MP make_pair

#define SZ(a) int((a).size())



//#define LOCAL 1

#ifdef LOCAL

#define DEBUG(s) cout << (s) << endl

#define dump(x)  cerr << #x << " = " << (x) << endl

#define BR cout << endl;

#else

#define DEBUG(s) do{}while(0)

#define dump(x) do{}while(0)

#define BR

#endif



//改造

typedef long long int ll;

using namespace std;





int main() {

    int a,b;

    cin >> a >> b;

    if( a + b >= 10) cout << "error" << endl;

    else cout << a + b << endl;

}
