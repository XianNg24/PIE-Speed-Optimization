#include<bits/stdc++.h>

#define rep(i,n)for(int i=0;i<n;i++)

using namespace std;

typedef pair<int, int>P;



int w[2], h[2], l[2][500][500], sx[2], sy[2], r;

int dx[]{ 1,-1,0,0 }, dy[]{ 0,0,1,-1 };

int ans[2][100001], d[250000];

bool vis[500][500], used[500][500];

list<P>que[250000];

int compress(int k) {

	vector<int>x;

	rep(i, h[k])rep(j, w[k])x.push_back(l[k][i][j]);

	sort(x.begin(), x.end());

	x.erase(unique(x.begin(), x.end()), x.end());

	rep(i, x.size())d[i] = x[i];

	rep(i, h[k])rep(j, w[k])

		l[k][i][j] = lower_bound(x.begin(), x.end(), l[k][i][j]) - x.begin();

	return x.size();

}

void solve(int k) {

	ans[k][0] = 0;

	queue<P>Q;

	int n = compress(k);

	rep(i, n)que[i].clear();

	memset(vis, 0, sizeof(vis));

	memset(used, 0, sizeof(used));

	Q.push(P(sx[k], sy[k]));

	vis[sx[k]][sy[k]] = true;

	int cnt = 0, Max = 0;

	while (1) {

		while (!Q.empty()) {

			P p = Q.front(); Q.pop();

			if (used[p.first][p.second])continue;

			used[p.first][p.second] = true;

			cnt++; if (cnt >= r)break;

			rep(i, 4) {

				int nx = p.first + dx[i], ny = p.second + dy[i];

				if (0 <= nx&&nx < h[k] && 0 <= ny&&ny < w[k] && !vis[nx][ny]) {

					vis[nx][ny] = true;

					if (l[k][nx][ny] <= Max)Q.push(P(nx, ny));

					else que[l[k][nx][ny]].push_back(P(nx, ny));

				}

			}

		}

		ans[k][cnt] = min(ans[k][cnt], d[Max]);

		for (int i = Max; i < n; i++) {

			if (!que[i].empty()) {

				Max = i;

				for (P p : que[i])Q.push(p);

				que[i].clear();

				break;

			}

		}

		if (cnt >= r || Q.empty())break;

	}

	for (int i = r - 1; i >= 1; i--)ans[k][i] = min(ans[k][i], ans[k][i + 1]);

}

int main() {

	while (scanf("%d", &r), r) {

		rep(k, 2) {

			scanf("%d%d%d%d", &w[k], &h[k], &sy[k], &sx[k]); sx[k]--; sy[k]--;

			rep(i, h[k])rep(j, w[k])scanf("%d", &l[k][i][j]);

		}

		fill(ans[0], ans[2], INT_MAX);

		rep(k, 2)solve(k);

		int Min = INT_MAX;

		for (int i = 0; i <= r; i++) {

			if (ans[0][i] == INT_MAX || ans[1][r - i] == INT_MAX)continue;

			Min = min(Min, ans[0][i] + ans[1][r - i]);

		}

		printf("%d\n", Min);

	}

}