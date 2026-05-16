#include <bits/stdc++.h>

#define INF 5000000000000000000

#define ll long long

#define pll pair<ll, ll>

using namespace std;



ll N, M, Q;

vector<vector<ll>> pattern(vector<vector<ll>> A)

{

  vector<vector<ll>> res;

  if (A.at(0).size() == N) {

    return A;

  }

  for (ll j = 0; j < A.size(); ++j) {

    ll last = A.at(j).at(A.at(j).size() - 1);

    for (ll k = last; k <= M; ++k) {

      vector<ll> temp = A.at(j);

      temp.push_back(k);

      res.push_back(temp);

    }

  }

  return pattern(res);

}



int main()

{

  cin >> N >> M >> Q;

  vector<vector<ll>> A;

  for (ll i = 1; i <= M; ++i) {

    A.push_back({i});

  }

  vector<vector<ll>> abcd(Q);

  for (ll i = 0; i < Q; ++i) {

    ll a, b, c, d;

    cin >> a >> b >> c >> d;

    a -= 1;

    b -= 1;

    abcd.at(i) = {a, b, c, d};

  }



  vector<vector<ll>> all = pattern(A);

  // for (ll i = 0; i < all.size(); ++i) {

  //   for (ll j = 0; j < all.at(i).size(); ++j) {

  //     cout << all.at(i).at(j) << ' ';

  //   }

  //   cout << endl;

  // }

  ll ans = 0;

  for (ll i = 0; i < all.size(); ++i) {

    vector<ll> check = all.at(i);

    ll score = 0;

    for (ll j = 0; j < Q; ++j) {

      vector<ll> now = abcd.at(j);

      ll a = now.at(0), b = now.at(1), c = now.at(2), d = now.at(3);

      if (check.at(b) - check.at(a) == c) {

        score += d;

      }

    }

    ans = max(ans, score);

  }

  cout << ans << endl;

}
