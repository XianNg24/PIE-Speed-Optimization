#include<iostream>

#include<vector>

#include<list>

#define PB push_back

#define rep(i,x) for(int i=0;i<x;i++)

using namespace std;

int main(){

    int n,m;

    while(cin>>n>>m,n||m){

        vector<vector<int> >H(n+1);

        list<int>L1,L2;

        int a,b;

        while(m--){

            cin>>a>>b;

            H[a].PB(b);

            H[b].PB(a);

        }

        rep(i,H[1].size())L1.PB(H[1][i]);

        list<int>::iterator ite=L1.begin();

        for(;ite!=L1.end();ite++){

            rep(i,H[*ite].size()){

                L2.PB(H[*ite][i]);

            }

        }

        L1.sort();L2.sort();

        L1.merge(L2);

        L1.unique();

        int ans=L1.size();

        if(ans>0)ans--;

        cout<<ans<<endl;

    }

}