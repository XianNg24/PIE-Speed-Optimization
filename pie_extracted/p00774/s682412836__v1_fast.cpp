#include<bits/stdc++.h>

using namespace std;

#define FOR(i,bg,ed) for(int i=bg;i<ed;i++)

#define REP(i,n) FOR(i,0,n)



typedef pair<int,int> p;

const int INF =1e5;

int R,C=5;

p b[100][100];

bool nb[100][100];

bool f(){

 bool ret = false;

 FOR(i,1,C-1)REP(j,R){

   nb[i][j]=false;

   if(b[i][j].first == INF)continue;

   if(b[i][j].second == b[i-1][j].second)

   if(b[i][j].second == b[i+1][j].second)

     ret = nb[i][j]=true;

 }

 FOR(i,1,C-1)REP(j,R){

    if(nb[i][j]){

       b[i-1][j]={INF,-1};

       b[i][j]={INF,-1};

       b[i+1][j]={INF,-1};   	   

   	}

 }

 REP(i,C){

   sort(b[i],b[i]+R); 

 }

 return ret;

}

int main(){

  while(cin>>R,R){

   REP(i,R)REP(j,C){

     int val;

     cin>>val;

     b[j][R-i-1]={R-i-1,val};

   }

   int ret = 0;

   REP(i,C)REP(j,R)if(b[i][j].second>-1)ret+=b[i][j].second;

   while(f());

   REP(i,C)REP(j,R)if(b[i][j].second>-1)ret-=b[i][j].second;

   cout<<ret<<endl;

  }

  

}
