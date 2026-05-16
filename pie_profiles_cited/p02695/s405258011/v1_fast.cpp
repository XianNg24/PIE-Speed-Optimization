#include <bits/stdc++.h>

#define INF 5000000000000000000

#define ll long long

#define pll pair<ll, ll>

using namespace std;



ll N, M, Q;

ll ans = 0;

vector<ll> A;

vector<vector<ll>> abcd;

void rep(ll index, ll last)

{

  if (index == N) {

    ll temp = 0;

    for (ll i = 0; i < Q; ++i) {

      if (A.at(abcd.at(i).at(1)) - A.at(abcd.at(i).at(0)) == abcd.at(i).at(2)) {

        temp += abcd.at(i).at(3);

      }

    }

    ans = max(ans, temp);

    return;

  }

  for (ll i = last; i <= M; ++i) {

    A.at(index) = i;

    rep(index + 1, i);

  }

}



int main()

{

  cin >> N >> M >> Q;

  A = vector<ll>(N);

  abcd = vector<vector<ll>>(Q);

  for (ll i = 0; i < Q; ++i) {

    ll a, b, c, d;

    cin >> a >> b >> c >> d;

    a -= 1;

    b -= 1;

    abcd.at(i) = {a, b, c, d};

  }

  rep(0, 1);

  cout << ans << endl;

}
