#include <bits/stdc++.h>



#define rng(i, a, b) for (int i = int(a); i < int(b); i++)

#define rep(i, b) rng(i, 0, b)

#define gnr(i, a, b) for (int i = int(b) - 1; i >= int(a); i--)

#define per(i, b) gnr(i, 0, b)



using namespace std;



using ll = long long;

using P = pair<int, int>;



int main() {

  string s, t;

  cin >> s >> t;

  bool ok = false;

  rep(i, 100) {

    s = s.back() + s.substr(0, s.size() - 1);

    if (s == t) {

      ok = true;

      break;

    }

  }

  cout << (ok ? "Yes" : "No") << endl;

  return 0;

}
