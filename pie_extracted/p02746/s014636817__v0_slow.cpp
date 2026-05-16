#include <bits/stdc++.h>

using namespace std;



using ll = long long;

using Pi = pair<int, int>;

using Pl = pair<ll, ll>;

using vint = vector<int>;

using vvint = vector<vint>;

using vvvint = vector<vvint>;

using vdouble = vector<double>;

using vvdouble = vector<vdouble>;

using vvvdouble = vector<vvdouble>;

using vll = vector<ll>;

using vvll = vector<vll>;

using vvvll = vector<vvll>;

using uint = unsigned int;

using ull = unsigned long long;



template<typename T> using uset = unordered_set<T>;

template<typename T1, typename T2> using umap = unordered_map<T1, T2>;



constexpr int INF = (1 << 30) - 1;

constexpr ll LLINF = 1LL << 60;

constexpr int dy[] = {1, 0, -1, 0, 1, -1, -1, 1};

constexpr int dx[] = {0, 1, 0, -1, 1, 1, -1, -1};

constexpr char el = '\n';

constexpr int mod = 1000000007;



template<typename T> T gcd(T a, T b) { return (b ? gcd(b, a % b) : a); }

template<typename T> T lcm(T a, T b) { return (a / gcd(a, b) * b); }

template<typename T1, typename T2>

inline bool chmin(T1 &a, T2 b) { return (a > b && (a = b, true)); }

template<typename T1, typename T2>

inline bool chmax(T1 &a, T2 b) { return (a < b && (a = b, true)); }



template<typename T>

ostream& operator <<(ostream &os, vector<T> &v) {

	os << v[0];

	for (int i = 1; i < v.size(); i++) os << " " << v[i];

	return (os);

}



template<typename T>

istream& operator >>(istream &is, vector<T> &v) {

	for (auto &u : v) is >> u; return (is);

}



template<typename T1, typename T2>

istream& operator >>(istream &is, pair<T1, T2> &p) {

	return (is >> p.first >> p.second);

}



ll pow3[33];



ll calc(ll a, ll b, ll c, ll d, ll size = 30) {

	ll div = pow3[size-1];

	ll parta = a / div, partb = b / div;

	ll partc = c / div, partd = d / div;

	ll spath = abs(d-b) + abs(c-a);

	if (parta == partc && partb == partd) {

		return (calc(a - parta*div, b - partb*div, c - partc*div, d - partd*div, size-1));

	}

	

	//やばいやつら

	if (parta == partc || partb == partd) {

		if (partb == partd) { swap(a, b); swap(c, d); swap(parta, partb); swap(partc, partd); }

		if (parta == 1) {

			return (abs(d-b) + min(a-div+1+c-div+1, 2*div-a+2*div-c));

		}

		a -= parta*div, c -= partc*div;

		for (ll sz = size-2; sz >= 0; sz--) {

			ll dv = pow3[sz];

			ll pta = a/dv, ptc = c/dv;

			if (pta != ptc) return (spath);

			if (pta == ptc && pta == 1 && abs(d-b) / dv > 1) return (abs(d-b) + min(a-dv+1+c-dv+1, 2*dv-a+2*dv-c));

			a -= pta*dv, c -= ptc*dv;

		}

	}

	return (spath);

}



void solve() {

	ll a, b, c, d; cin >> a >> b >> c >> d; --a, --b, --c, --d;

	cout << calc(a, b, c, d) << endl;

}



void Main() {

	//init

	pow3[0] = 1;

	for (int i = 1; i <= 30; i++) pow3[i] = pow3[i-1] * 3;



	int Q; cin >> Q;

	while (Q--) solve();

}



int main() {

	cin.tie(0);

	ios::sync_with_stdio(0);

	cout << fixed << setprecision(20);

	Main();

	return (0);

}
