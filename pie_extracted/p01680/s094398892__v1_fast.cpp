#include<bits/stdc++.h>

using namespace std;

using LL = long long; using ll = LL;

using PLL = pair<LL, LL>; using pll = PLL;

using PII = pair<int, int>; using pii = PII;

const int INF = 1e9; const LL LINF = 1e18;

#define SZ(a) (int)a.size()

#define FOR(i,s,t) for(int i= s; i<t;i++)

#define ALL(a) a.begin(),a.end()

using VL = vector<LL>; using VLL = vector<VL>;



struct UnionFind {

	vector<int> data;

	UnionFind(int size) { init(size); }

	void init(int size) { data.clear(); data.resize(size, -1); }

	bool unite(int x, int y) {

		x = root(x); y = root(y);

		if (x != y) {

			if (data[y] < data[x]) swap(x, y);

			data[x] += data[y]; data[y] = x;

		}

		return x != y;

	}

	bool same(int x, int y) {

		return root(x) == root(y);

	}

	int root(int x) {

		return data[x] < 0 ? x : data[x] = root(data[x]);

	}

	int size(int x) {

		return -data[root(x)];

	}

};



void solve() {

	int N, M;

	while (cin >> N >> M, N) {

		UnionFind uf(N);

		FOR(i, 0, M) {

			int a, b;

			cin >> a >> b;

			a--, b--;

			uf.unite(a, b);

		}

		VL used(N, 0);

		int isgroup = 0;

		int cnt = 0;

		FOR(i, 0, N) {

			int root = uf.root(i);

			if (used[root])continue;

			cnt++;

			if (uf.size(root) != 1)isgroup=1;

			used[root] = 1;

		}

		LL nene = 1;

		const LL mod = 1e9 + 7;



		FOR(i, 0, cnt) {

			nene *= 2;

			nene %= mod;

		}

		nene += isgroup;

		nene %= mod;

		cout << nene << endl;

	}



}



int main() {

	cin.tie(0);

	ios_base::sync_with_stdio(false);

	solve();

	return 0;

}
