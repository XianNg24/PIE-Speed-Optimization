#include<bits/stdc++.h>

using namespace std;

 

template<typename T1, typename T2> istream& operator>>(istream& is, pair<T1,T2>& a){ return is >> a.first >> a.second; }

template<typename T1, typename T2> ostream& operator<<(ostream& os, pair<T1,T2>& a){ return os << a.first << " " << a.second; }

template<typename T> istream& operator>>(istream& is, vector< T >& vc){ for(int i = 0; i < vc.size(); i++) is >> vc[i]; return is; }

template<typename T> ostream& operator<<(ostream& os, vector< T >& vc){ for(int i = 0; i < vc.size(); i++) os << vc[i] << endl; return os; }

 

#define ForEach(it,c) for(__typeof (c).begin() it = (c).begin(); it != (c).end(); it++)

#define ALL(v) (v).begin(), (v).end()

#define UNQ(s) { sort(ALL(s)); (s).erase( unique( ALL(s)), (s).end());}



typedef long long int64;

typedef pair< int , int > Pi;

typedef pair< int , Pi > Pii;

const int INF = 1 << 30;



int main()

{

  int R, W[2], H[2], X, Y, L[500][500];

  int min_cost[500][500], limit[2][500 * 500 + 1];



  static const signed dy[] = { 0, 1, 0, -1}, dx[] = { 1, 0, -1, 0};



  while(cin >> R, R){

    map< int, int > level[2];

    for(int i = 0; i < 2; i++){

      cin >> W[i] >> H[i] >> X >> Y;

      --X, --Y;

      for(int j = 0; j < H[i]; j++){

        for(int k = 0; k < W[i]; k++){

          cin >> L[j][k];

        }

      }

      priority_queue< Pii, vector< Pii >, greater< Pii > > que;

      fill_n( *min_cost, 500 * 500, INF);

      que.push( Pii( L[Y][X], make_pair( X, Y)));

      min_cost[X][Y] = L[Y][X];

      level[i][min_cost[X][Y]]++;

      while(!que.empty()){

        Pii p = que.top(); que.pop();

        if(p.first > min_cost[p.second.first][p.second.second]) continue;

        for(int j = 0; j < 4; j++){

          int nx = p.second.first + dx[j], ny = p.second.second + dy[j];

          if(nx < 0 || nx >= W[i] || ny < 0 || ny >= H[i]) continue;

          if(max( L[ny][nx], p.first) >= min_cost[nx][ny]) continue;

          min_cost[nx][ny] = max( L[ny][nx], p.first);

          que.push( Pii( max( L[ny][nx], p.first), make_pair( nx, ny)));

          level[i][min_cost[nx][ny]]++;

        }

      }



      int sz = 0;

      fill_n( limit[i], H[i] * W[i], 0);

      ForEach(it, level[i]){

        sz += it -> second;

        limit[i][sz] = it -> first;

      }

      for(int j = H[i] * W[i] - 1; j > 0; j--){

        if(limit[i][j] == 0) limit[i][j] = limit[i][j + 1];

      }

    }



    int ret = INF;

    for(int i = 0; i < H[0] * W[0]; i++){

      int nokori = R - i;

      if(nokori < 0 || nokori > W[1] * H[1]) continue;

      ret = min( ret, limit[0][i] + limit[1][nokori]);

    }

    cout << ret << endl;

  }

}