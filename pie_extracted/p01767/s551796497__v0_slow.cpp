#include<bits/stdc++.h>

using namespace std;

#define int long long

int N,M;

vector<int>A,B,C;



signed main(){

    cin>>N;A.resize(N);

    for(int i=0;i<N;i++)cin>>A[i];

    cin>>M;

    B.resize(M);C.resize(M);

    for(int i=0;i<M;i++)cin>>B[i];

    for(int i=0;i<M;i++)cin>>C[i];



    sort(A.begin(),A.end());

    vector<int>sum(N);

    for(int i=0;i<N;i++){

        sum[i]=A[i]+(i?sum[i-1]:0);

    }





    for(int i=0;i<M;i++){

        int u=upper_bound(A.begin(),A.end(),B[i])-A.begin();

        int val;

        if(u==0)val=0;

        else val=sum[u-1];

        if(C[i]<=val)cout<<"Yes"<<endl;

        else cout<<"No"<<endl;

    }

    return 0;

}