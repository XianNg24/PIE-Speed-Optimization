#include<bits/stdc++.h>

using namespace std;

typedef long long ll;

struct edge{ll to,cost;};

#define MAX 2005

ll inf = 20000000;

ll INF = inf*3000LL;



int N,M,K;

vector<edge> G[MAX];



ll DP[MAX][MAX];

ll dp[MAX][MAX][2];

ll V[MAX];



bool visited[MAX];

vector<ll> A,B;



void calc(bool flg){

  int size=A.size();

  dp[0][1-flg][1-flg]=-INF;  

  dp[0][flg][flg]=0;

  for(int i=1;i<size;i++){

    for(int j=0;j<=size;j++){

      dp[i][j][0]=max(dp[i-1][j][1],dp[i-1][j][0]);

      V[j]=max(V[j],dp[i][j][0]);

      if(j==0)continue;

      ll cost=max(dp[i-1][j-1][0],dp[i-1][j-1][1]+B[i-1]);

      if(i+1==size&&A.size()==B.size()&&flg){

        cost+=B[i];

      }

      dp[i][j][1]=cost;

      V[j]=max(V[j],dp[i][j][1]);

    }

  }



}



void dfs(int pos,int prev){

  if(visited[pos])return;

  visited[pos]=true;

  A.push_back(pos);

  for(int i=0;i<(int)G[pos].size();i++){

    if(G[pos][i].to==prev)continue;

    B.push_back(G[pos][i].cost);

    dfs(G[pos][i].to,pos);

    break;

  }

}



int search(int p){

  map<int,bool> mp;

  while(!mp[p]){

    mp[p]=true;

    for(int i=0;i<(int)G[p].size();i++){

      edge e=G[p][i];

      if(!mp[e.to]){

        p=e.to;

        break;

      }

    }

  }

  return p;

}



int main(){

  cin>>N>>M>>K;

  for(int i=0;i<M;i++){

    ll a,b,c;

    cin>>a>>b>>c;

    if(c==0)c=-INF;

    G[a].push_back((edge){b,c});

    G[b].push_back((edge){a,c});

  }

  

  for(int i=0;i<MAX;i++)

    for(int j=0;j<MAX;j++)

      DP[i][j]=dp[i][j][0]=dp[i][j][1]=-INF;

  

  DP[0][0]=0;



  int C=0;

  for(int i=1;i<=N;i++){

    if(visited[i])continue;

    A.clear();

    B.clear();

    dfs( search(i) ,0);

    int size=A.size();

    fill(V,V+MAX,-INF);

    V[0]=V[1]=0;

    calc(true);

    calc(false);

    C++; 

    for(int j=0;j<=K;j++)

      for(int k=0;k<=min(j,size);k++)

        DP[C][j]=max(DP[C][j],DP[C-1][j-k]+V[k]);

  }

 

  if(DP[C][K] < -inf) cout << "Impossible" << endl;

  else cout << DP[C][K] << endl;

  return 0;

}