#include<bits/stdc++.h>

#define rep(i,n)for(int i=0;i<n;i++)

using namespace std;



int ans[2][100001], w, h, x, y, f[500][500];

int dx[]{ 1,-1,0,0 }, dy[]{ 0,0,1,-1 };

bool used[500][500];

struct st {

	int x, y, c;

};

bool operator<(st a, st b) {

	return a.c > b.c;

}

int main() {

	int r;

	while (scanf("%d", &r), r) {

		fill(ans[0], ans[2], INT_MAX);

		rep(i, 2) {

			memset(used, 0, sizeof(used));

			ans[i][0] = 0;

			scanf("%d%d%d%d", &w, &h, &y, &x);

			x--; y--;

			rep(j, h)rep(k, w)scanf("%d", &f[j][k]);

			priority_queue<st>que;

			que.push({ x,y,1 });

			used[x][y] = true;

			int cnt = 0, Max = 0;

			while (!que.empty()) {

				st s = que.top(); que.pop(); cnt++;

				Max = max(Max, s.c);

				ans[i][cnt] = min(ans[i][cnt], Max);

				if (cnt >= r)break;

				rep(j, 4) {

					int nx = s.x + dx[j], ny = s.y + dy[j];

					if (0 <= nx&&nx < h && 0 <= ny&&ny < w && !used[nx][ny]) {

						used[nx][ny] = true;

						que.push({ nx,ny,f[nx][ny] });

					}

				}

			}

			for (int j = r - 1; j > 0; j--)

				ans[i][j] = min(ans[i][j], ans[i][j + 1]);

		}

		int Min = INT_MAX;

		rep(i, r + 1) {

			if (ans[0][i] == INT_MAX || ans[1][r - i] == INT_MAX)continue;

			Min = min(Min, ans[0][i] + ans[1][r - i]);

		}

		printf("%d\n", Min);

	}

}